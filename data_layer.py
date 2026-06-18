"""AIDA data layer — upload many files -> one cohesive SQL database.

`DataLayer` keeps one DuckDB database file per *project*, holding many related tables.
Heterogeneous files (CSV, TSV, JSON/NDJSON, Parquet, Excel) — or a snapshot of a live
Postgres schema — each become a SQL table in the same `.duckdb` file, with normalized
column names. Relationships between tables are auto-detected, and the full schema can
be exported via `schema_text()` / `schema_json()` — the hand-off contract the
downstream auto-EDA step and NL -> SQL chatbot consume.
"""

import os
import re
import pathlib

import duckdb
import pandas as pd

__all__ = ["DataLayer", "clean_column_name"]

AIDA_DUCKDB_DIR = os.getenv(
    "AIDA_DUCKDB_DIR", str(pathlib.Path(__file__).resolve().parent / "files" / "duckdb")
)
MAX_ROW_THRESHOLD = 200_000


def clean_column_name(name: str) -> str:
    """Normalize a column name to a safe snake_case identifier."""
    name = str(name).strip().lower()
    name = re.sub(r"[^\w]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"_{name}"
    return name


class DataLayer:
    """One cohesive DuckDB database per *project*, holding many related tables."""

    _READERS = {
        ".csv":     "read_csv_auto({p})",
        ".txt":     "read_csv_auto({p})",
        ".tsv":     "read_csv({p}, delim='\\t')",
        ".parquet": "read_parquet({p})",
        ".pq":      "read_parquet({p})",
        ".json":    "read_json_auto({p})",
        ".ndjson":  "read_json_auto({p})",
    }

    def __init__(self, project: str, base_dir: str = AIDA_DUCKDB_DIR):
        self.project = clean_column_name(project)
        self.base_dir = pathlib.Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / f"{self.project}.duckdb"
        self.con = duckdb.connect(str(self.db_path))
        # Populated by _rename_columns: table_name -> [{original, cleaned, changed}]
        self.column_renames: dict[str, list[dict]] = {}

    def __enter__(self) -> "DataLayer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def ingest_file(self, file_path: str, table_name: str | None = None,
                    if_exists: str = "replace") -> str:
        if if_exists not in ("skip", "replace", "error"):
            raise ValueError(f"if_exists must be 'skip', 'replace', or 'error', got {if_exists!r}")

        path = pathlib.Path(file_path)
        if table_name is None:
            table_name = clean_column_name(path.stem)
        ext = path.suffix.lower()

        if self.table_exists(table_name):
            if if_exists == "skip":
                return table_name
            if if_exists == "error":
                raise ValueError(
                    f"Table '{table_name}' already exists in project '{self.project}'"
                )

        if ext in self._READERS:
            reader = self._READERS[ext].format(p="?")
            self.con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {reader}",
                [str(path)],
            )
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)
            self.con.register("temp_excel_df", df)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM temp_excel_df")
            self.con.unregister("temp_excel_df")
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        self._rename_columns(table_name)
        return table_name

    def ingest_files(self, file_paths, if_exists: str = "replace") -> list[str]:
        tables = []
        for item in file_paths:
            if isinstance(item, (tuple, list)):
                path, name = item
            else:
                path, name = item, None
            tables.append(self.ingest_file(str(path), table_name=name, if_exists=if_exists))
        return tables

    def ingest_postgres(self, dsn: str | None = None, *, pg_schema: str = "public",
                        only: list[str] | None = None, prefix: str = "",
                        if_exists: str = "replace") -> list[str]:
        if if_exists not in ("skip", "replace", "error"):
            raise ValueError(f"if_exists must be 'skip', 'replace', or 'error', got {if_exists!r}")
        dsn = dsn or os.getenv("AIDA_PG_DSN")
        if not dsn:
            raise ValueError("No Postgres DSN given and the AIDA_PG_DSN env var is not set")

        self.con.execute("INSTALL postgres")
        self.con.execute("LOAD postgres")

        safe_dsn = dsn.replace("'", "''")
        self.con.execute(f"ATTACH '{safe_dsn}' AS _pg (TYPE postgres, READ_ONLY)")
        try:
            rows = self.con.execute(
                """SELECT table_name
                   FROM _pg.information_schema.tables
                   WHERE table_schema = ? AND table_type = 'BASE TABLE'
                   ORDER BY table_name""",
                [pg_schema],
            ).fetchall()
            pg_tables = [r[0] for r in rows]
            if only is not None:
                wanted = set(only)
                pg_tables = [t for t in pg_tables if t in wanted]

            created = []
            for t in pg_tables:
                local = clean_column_name(f"{prefix}{t}")
                if self.table_exists(local):
                    if if_exists == "skip":
                        created.append(local)
                        continue
                    if if_exists == "error":
                        raise ValueError(
                            f"Table '{local}' already exists in project '{self.project}'"
                        )
                self.con.execute(
                    f'CREATE OR REPLACE TABLE {local} AS '
                    f'SELECT * FROM _pg.{pg_schema}."{t}"'
                )
                self._rename_columns(local)
                created.append(local)
            return created
        finally:
            self.con.execute("DETACH _pg")

    def _rename_columns(self, table_name: str):
        cols = [row[0] for row in self.con.execute(f"DESCRIBE {table_name}").fetchall()]
        col_map: dict[str, str] = {}
        seen: set[str] = set()
        for col in cols:
            cleaned = clean_column_name(col)
            base, i = cleaned, 1
            while cleaned in seen:
                cleaned = f"{base}_{i}"
                i += 1
            seen.add(cleaned)
            col_map[col] = cleaned
        for old, new in col_map.items():
            if old != new:
                self.con.execute(f'ALTER TABLE {table_name} RENAME COLUMN "{old}" TO "{new}"')
        self.column_renames[table_name] = [
            {"original": col, "cleaned": col_map[col], "changed": col != col_map[col]}
            for col in cols
        ]

    def table_exists(self, table_name: str) -> bool:
        res = self.con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table_name]
        ).fetchone()
        return res is not None

    def list_tables(self) -> list[str]:
        return [row[0] for row in self.con.execute("SHOW TABLES").fetchall()]

    def columns(self, table_name: str) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.con.execute(f"DESCRIBE {table_name}").fetchall()]

    def query(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()

    def materialize_df(self, table_name: str, max_rows: int = MAX_ROW_THRESHOLD) -> pd.DataFrame:
        res = self.con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        total = res[0] if res else 0
        if total <= max_rows:
            return self.con.execute(f"SELECT * FROM {table_name}").df()
        return self.con.execute(f"SELECT * FROM {table_name} LIMIT {max_rows}").df()

    def _column_stats(self, table_name: str, column: str) -> tuple[int, int]:
        r = self.con.execute(
            f'SELECT COUNT(*), COUNT(DISTINCT "{column}") FROM {table_name}').fetchone()
        return (r[0], r[1]) if r else (0, 0)

    def detect_relationships(self, min_overlap: float = 0.5) -> list[dict]:
        tables = self.list_tables()
        col_locations: dict[str, list[dict]] = {}
        for t in tables:
            for col, _typ in self.columns(t):
                rows, distinct = self._column_stats(t, col)
                col_locations.setdefault(col, []).append(
                    {"table": t, "rows": rows, "distinct": distinct,
                     "unique": rows > 0 and distinct == rows}
                )

        rels = []
        for col, locs in col_locations.items():
            if len(locs) < 2:
                continue
            looks_like_id = col == "id" or col.endswith("_id")
            for i in range(len(locs)):
                for j in range(len(locs)):
                    if i == j:
                        continue
                    pk, fk = locs[i], locs[j]
                    if not pk["unique"]:
                        continue
                    if fk["unique"] and pk["table"] > fk["table"]:
                        continue
                    frac = self._match_fraction(fk["table"], col, pk["table"], col)
                    if frac < min_overlap:
                        continue
                    confidence = round(min(1.0, frac * (1.0 if looks_like_id else 0.7)), 2)
                    rels.append({
                        "from_table": fk["table"], "from_column": col,
                        "to_table": pk["table"], "to_column": col,
                        "match_fraction": round(frac, 3), "confidence": confidence,
                    })
        rels.sort(key=lambda r: r["confidence"], reverse=True)
        return rels

    def _match_fraction(self, fk_table: str, fk_col: str, pk_table: str, pk_col: str) -> float:
        try:
            r = self.con.execute(f'''
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT CAST("{fk_col}" AS VARCHAR) AS v
                    FROM {fk_table} WHERE "{fk_col}" IS NOT NULL
                ) f
                WHERE f.v IN (SELECT CAST("{pk_col}" AS VARCHAR) FROM {pk_table})
            ''').fetchone()
            matched = r[0] if r else 0
            d = self.con.execute(
                f'SELECT COUNT(DISTINCT "{fk_col}") FROM {fk_table} WHERE "{fk_col}" IS NOT NULL'
            ).fetchone()
            total = d[0] if d else 0
            return matched / total if total else 0.0
        except Exception:
            return 0.0

    def schema_json(self) -> dict:
        tables = []
        for t in self.list_tables():
            n = self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            tables.append({
                "name": t,
                "row_count": n,
                "columns": [{"name": c, "type": typ} for c, typ in self.columns(t)],
            })
        return {
            "project": self.project,
            "db_path": str(self.db_path.resolve()),
            "tables": tables,
            "relationships": self.detect_relationships(),
        }

    def schema_text(self) -> str:
        s = self.schema_json()
        lines = [f"DATABASE: {s['project']}  ({len(s['tables'])} tables)", ""]
        for t in s["tables"]:
            lines.append(f"TABLE {t['name']}  ({t['row_count']} rows)")
            for c in t["columns"]:
                lines.append(f"    {c['name']:<24} {c['type']}")
            lines.append("")
        if s["relationships"]:
            lines.append("RELATIONSHIPS (auto-detected):")
            for r in s["relationships"]:
                lines.append(
                    f"    {r['from_table']}.{r['from_column']} -> "
                    f"{r['to_table']}.{r['to_column']}  "
                    f"(match {r['match_fraction']:.0%}, confidence {r['confidence']})"
                )
        else:
            lines.append("RELATIONSHIPS: none detected")
        return "\n".join(lines)

    def close(self):
        self.con.close()
