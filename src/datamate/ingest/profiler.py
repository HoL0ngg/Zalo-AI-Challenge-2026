import duckdb


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def profile_table(connection: duckdb.DuckDBPyConnection, table: str) -> dict:
    source = quote(table)
    count = connection.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    columns = []
    for name, dtype, *_ in connection.execute(f"DESCRIBE {source}").fetchall():
        col = quote(name)
        nulls, distinct, low, high = connection.execute(
            f"SELECT count(*) FILTER (WHERE {col} IS NULL), count(DISTINCT {col}), "
            f"min({col}), max({col}) FROM {source}"
        ).fetchone()
        samples = [row[0] for row in connection.execute(
            f"SELECT DISTINCT {col} FROM {source} WHERE {col} IS NOT NULL ORDER BY 1 LIMIT 5"
        ).fetchall()]
        columns.append(dict(name=name, type=dtype, null_ratio=nulls / count if count else 0,
                            distinct=distinct, min=low, max=high, samples=samples))
    return {"rows": count, "columns": columns}
