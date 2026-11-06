"""Runs the SQL stages of sql/ in order on an in-memory DuckDB connection."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .. import config


def calendar() -> pd.DataFrame:
    rows = []
    for wid in config.week_ids():
        start, end = config.week_bounds(wid)
        rows.append({"semana": wid, "inicio": start, "fim": end, "data_pagamento": config.payment_date(wid)})
    return pd.DataFrame(rows)


def connect(tables: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, df in tables.items():
        con.register(f"raw_{name}", df)
    con.register("cal_weeks", calendar())
    con.execute(f"SET VARIABLE tol_line = {config.TOLERANCE_LINE_CENTS}")
    con.execute(f"SET VARIABLE tol_repasse = {config.TOLERANCE_REPASSE_CENTS}")
    con.execute(f"SET VARIABLE sim_min = {config.BANK_NAME_SIMILARITY_MIN}")
    con.execute(f"SET VARIABLE sim_strong = {config.BANK_NAME_SIMILARITY_STRONG}")
    con.execute(f"SET VARIABLE bank_window = {config.BANK_DATE_WINDOW_DAYS}")
    return con


def stage_files(sql_dir: Path = config.SQL_DIR) -> list[Path]:
    return sorted(p for p in sql_dir.glob("*.sql") if p.name[:2].isdigit())


def run_stage(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text(encoding="utf-8"))


def run_stages(con: duckdb.DuckDBPyConnection, up_to: str | None = None, start_at: str | None = None) -> list[str]:
    done = []
    for path in stage_files():
        if start_at and path.name < start_at:
            continue
        if up_to and path.name > up_to:
            break
        run_stage(con, path)
        done.append(path.name)
    return done
