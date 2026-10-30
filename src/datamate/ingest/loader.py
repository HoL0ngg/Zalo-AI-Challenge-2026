import io
import csv
import logging
import re
import sqlite3
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl import load_workbook

from datamate.core import BusinessContext
from datamate.ingest.canonical import build_canonical
from datamate.ingest.profiler import profile_table, quote
from datamate.ingest.readers import read_calendar, read_text
from datamate.linking.entity_index import build_entity_index


def from_rows(rows: list[tuple]) -> pd.DataFrame:
    if not rows:
        raise ValueError("Empty worksheet")
    # shortcut: densest text row among the first ten is the header; use metadata for ambiguous sheets later.
    header = max(range(min(10, len(rows))), key=lambda i: (
        sum(isinstance(v, str) and bool(v.strip()) for v in rows[i]), -i))
    names = [str(v).strip() if v is not None else f"column_{i + 1}" for i, v in enumerate(rows[header])]
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError("Duplicate column names")
    values = [row for row in rows[header + 1:] if any(v is not None for v in row)]
    while values and str(values[-1][0]).strip().casefold() in {"total", "tổng", "tổng cộng"}:
        values.pop()
    return pd.DataFrame(values, columns=names).infer_objects()


_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")
_AMBIGUOUS = re.compile(r"^-?\d{1,3}\.\d{3}$")  # 93.000 is a Vietnamese thousand-grouped number, not 93.0
_LEADING_ZERO = re.compile(r"^-?0\d")
_BOOLEAN = {"true": True, "false": False}


def coerce_csv_types(frame: pd.DataFrame) -> pd.DataFrame:
    """Typed columns from an all-text CSV, only where the reading cannot be ambiguous.

    pandas' own inference turns "10.000" into 10.0, which is a thousand times too small for a
    Vietnamese amount. Columns with grouped numbers, leading zeros (phones, codes) or mixed
    content stay text; the canonical layer parses them with explicit rules.
    """
    for column in frame.columns:
        values = frame[column].dropna().astype(str).str.strip()
        if values.empty:
            continue
        lowered = values.str.lower()
        if lowered.isin(_BOOLEAN).all():
            frame[column] = frame[column].map(lambda v: _BOOLEAN.get(str(v).strip().lower()) if pd.notna(v) else None)
        elif values.map(lambda v: bool(_INT.match(v))).all() and not values.map(lambda v: bool(_LEADING_ZERO.match(v))).any():
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        elif (values.map(lambda v: bool(_FLOAT.match(v) or _INT.match(v))).all()
              and not values.map(lambda v: bool(_AMBIGUOUS.match(v) or _LEADING_ZERO.match(v))).any()):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def read_tables(path: Path):
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1258")
        lines = text.splitlines()
        sample = "\n".join(line for line in lines[:20] if any(d in line for d in ",;\t|"))
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter if sample else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        header = max(range(min(10, len(rows))), key=lambda i: (len(rows[i]), -i))
        frame = pd.read_csv(io.StringIO(text), sep=delimiter, skiprows=header, dtype=str,
                            keep_default_na=False, na_values=[""])
        yield path.stem, coerce_csv_types(frame)
    elif path.suffix.lower() == ".xlsx":
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                yield sheet.title, from_rows(list(sheet.values))
        finally:
            book.close()
    elif path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            names = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                                       "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            for (name,) in names:
                yield name, pd.read_sql_query(f"SELECT * FROM {quote(name)}", connection)
        finally:
            connection.close()


class BusinessLoader:
    def __init__(self, root: Path, work: Path):
        self.root = root.resolve()
        self.work = work.resolve()
        if self.work.is_relative_to(self.root):
            raise ValueError("Temporary files must be outside input data")
        self.work.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, BusinessContext] = {}
        self.next_database = 0

    def load(self, business_id: str) -> BusinessContext:
        if business_id in self.cache:
            return self.cache[business_id]
        directory = (self.root / "data" / business_id).resolve()
        if not directory.is_relative_to(self.root / "data") or not directory.is_dir():
            raise ValueError("Missing or unsafe business directory")
        database = self.work / f"business_{self.next_database}.duckdb"
        self.next_database += 1
        profile, warnings = {}, []
        readme = read_text(directory / "README.md")
        rulebook = read_text(self.root / "rulebook.md")
        canonical = entities = None
        connection = duckdb.connect(str(database), config={"enable_external_access": "false"})
        try:
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() not in {".csv", ".xlsx", ".sqlite", ".sqlite3", ".db"}:
                    continue
                try:
                    if not path.resolve().is_relative_to(self.root):
                        raise ValueError("Input symlink escapes package")
                    for name, frame in read_tables(path):
                        if name.casefold() in {key.casefold() for key in profile}:
                            name = f"{path.stem}__{name}"
                        connection.register("input_frame", frame)
                        connection.execute(f"CREATE TABLE {quote(name)} AS SELECT * FROM input_frame")
                        connection.unregister("input_frame")
                        profile[name] = profile_table(connection, name)
                except Exception as error:
                    warnings.append(f"{path.name}: {error}")
                    logging.warning("Ingest: %s", warnings[-1])
            if profile:
                # Canonical views and the entity index are built in the same private database.
                canonical = build_canonical(connection, profile, readme, rulebook)
                warnings.extend(canonical.warnings)
                if canonical.complete:
                    try:
                        entities = build_entity_index(connection, list(canonical.views))
                    except Exception as error:  # noqa: BLE001
                        warnings.append(f"entity_index: {error}")
        finally:
            connection.close()
        if not profile:
            raise ValueError("No readable tables: " + "; ".join(warnings))
        context = BusinessContext(database, profile, readme, rulebook,
                                  read_calendar(self.root / "calendar.csv"), warnings,
                                  canonical=canonical, entities=entities,
                                  protected_values=entities.protected if entities else ())
        self.cache[business_id] = context
        return context
