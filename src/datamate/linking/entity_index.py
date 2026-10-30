"""Per-business entity index: every product, customer and category value that really exists.

Built once per business from the canonical views (so column names are already normalized).
A product is one record with its SKU, canonical name and every alias seen on sale lines
(case/NFD/typo variants of the display name), so variants of one entity never split into
several. Keys are NFC, diacritic-free, lowercase alphanumeric tokens joined by a space.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import duckdb

from datamate.understanding.textutil import clean, fold, has_diacritics

KIND_ORDER = {"product": 0, "customer": 1, "category": 2}


def entity_key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fold(clean(str(text)))))


@dataclass(frozen=True)
class EntityRecord:
    kind: str
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    table: str = ""
    column: str = ""


@dataclass
class EntityIndex:
    records: list[EntityRecord] = field(default_factory=list)
    exact: dict[str, list[int]] = field(default_factory=dict)        # key -> record indices
    id_keys: set[str] = field(default_factory=set)                   # keys that are identifiers
    protected: tuple[str, ...] = ()
    max_tokens: int = 1
    vocabulary: frozenset[str] = frozenset()   # tokens of all entity names: in-domain words

    def names_of(self, index: int) -> tuple[str, ...]:
        record = self.records[index]
        return (record.name, record.id, *record.aliases)

    def choices(self, kind: str) -> list[tuple[str, int]]:
        """(key, record index) for every name/alias of one kind, in a stable order."""
        seen: set[tuple[str, int]] = set()
        result = []
        for i, record in enumerate(self.records):
            if record.kind != kind:
                continue
            for name in (record.name, *record.aliases):
                key = entity_key(name)
                if key and (key, i) not in seen:
                    seen.add((key, i))
                    result.append((key, i))
        return sorted(result)


def _best_spelling(values: Iterable[str]) -> str:
    """Prefer the spelling with diacritics, then the most common, then alphabetical."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts, key=lambda v: (not has_diacritics(v), -counts[v], v))[0]


def _rows(connection: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    try:
        return connection.execute(sql).fetchall()
    except Exception:  # noqa: BLE001
        return []


def build_entity_index(connection: duckdb.DuckDBPyConnection, views: Sequence[str]) -> EntityIndex:
    """Index products, customers and categories from the canonical views present in `views`."""
    records: list[EntityRecord] = []
    aliases: dict[str, set[str]] = {}
    if "v_lines" in views:
        for sku, display in _rows(connection, "SELECT sku, display_name FROM v_lines "
                                              "WHERE sku IS NOT NULL AND display_name IS NOT NULL "
                                              "GROUP BY sku, display_name"):
            aliases.setdefault(str(sku), set()).add(clean(str(display)))
    names: dict[str, str] = {}
    categories: dict[str, list[str]] = {}
    if "v_products" in views:
        for sku, name, category in _rows(connection, "SELECT sku, name, category FROM v_products ORDER BY sku"):
            names[str(sku)] = clean(str(name))
            if category:
                categories.setdefault(entity_key(category), []).append(clean(str(category)))
    for sku in sorted(set(names) | set(aliases)):
        name = names.get(sku) or _best_spelling(aliases[sku])
        extra = sorted({a for a in aliases.get(sku, set()) if a and a != name})
        records.append(EntityRecord("product", sku, name, tuple(extra), "v_products", "name"))
    if "v_customers" in views:
        for cid, name in _rows(connection, "SELECT customer_id, name FROM v_customers WHERE name IS NOT NULL ORDER BY customer_id"):
            records.append(EntityRecord("customer", str(cid), clean(str(name)), (), "v_customers", "name"))
    for key in sorted(categories):
        if key:
            best = _best_spelling(categories[key])
            records.append(EntityRecord("category", best, best, (), "v_products", "category"))

    exact: dict[str, list[int]] = {}
    id_keys: set[str] = set()
    max_tokens = 1
    for i, record in enumerate(records):
        identifier = entity_key(record.id)
        if identifier and record.kind != "category":
            id_keys.add(identifier)
        for name in (record.name, record.id, *record.aliases):
            key = entity_key(name)
            if not key:
                continue
            bucket = exact.setdefault(key, [])
            if i not in bucket:
                bucket.append(i)
            max_tokens = max(max_tokens, key.count(" ") + 1)
    for bucket in exact.values():
        bucket.sort(key=lambda i: (KIND_ORDER[records[i].kind], records[i].id))
    protected = sorted({v for r in records for v in (r.name, *r.aliases) if v and len(entity_key(v)) >= 3})
    vocabulary = frozenset(t for key in exact for t in key.split() if not any(ch.isdigit() for ch in t))
    return EntityIndex(records, exact, id_keys, tuple(protected), min(max_tokens, 10), vocabulary)
