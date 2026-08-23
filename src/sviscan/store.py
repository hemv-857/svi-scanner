"""Deribit public chain fetcher + SQLite alert store."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx
import numpy as np

__all__ = [
    "alert_stats",
    "fetch_chain",
    "init_store",
    "load_latest_snapshot",
    "log_alert",
    "resolve_alerts",
    "save_quotes",
]


# ------------------------------------------------------------------ deribit
_BASE = "https://www.deribit.com/api/v2/public"


def fetch_chain(currency: str = "BTC", depth: int = 5) -> list[dict]:
    """All live option quotes normalized: (expiry_s, strike, iv_bid, iv_ask, mark_iv, spot)."""
    now_ms = time.time() * 1000
    with httpx.Client(timeout=30) as c:
        instruments = c.get(f"{_BASE}/get_instruments", params={"currency": currency, "kind": "option"}).json()["result"]
        out: dict[tuple, dict] = {}
        for ins in instruments:
            if ins["expiration_timestamp"] < now_ms + 6 * 3600e3:
                continue  # skip expiring within 6h
            ticker = c.get(f"{_BASE}/ticker", params={"instrument_name": ins["instrument_name"]}).json()["result"]
            bid_iv, ask_iv = ticker.get("bid_iv"), ticker.get("ask_iv")
            if bid_iv is None or ask_iv is None or bid_iv <= 0 or ask_iv <= 0:
                continue
            key = (ins["expiration_timestamp"] / 1000.0, float(ins["strike"]))
            rec = out.setdefault(key, {"T": key[0], "K": key[1],
                                       "iv_bid": bid_iv / 100.0,
                                       "iv_ask": ask_iv / 100.0,
                                       "mark_iv": (ticker.get("mark_iv") or 0) / 100.0,
                                       "spot": float(ticker.get("underlying_price") or np.nan),
                                       "n": 0})
            rec["n"] += 1
    return list(out.values())


# ------------------------------------------------------------------ storage
_SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    ts REAL, T REAL, K REAL, iv_bid REAL, iv_ask REAL, mark_iv REAL, spot REAL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at REAL, kind TEXT, expiry_short REAL, expiry_long REAL,
    k_min REAL, k_max REAL, severity REAL,
    quote_json TEXT, resolved_at REAL
);
"""


def init_store(path: str = "data/scanner.db") -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    con.commit()
    return con


def save_quotes(con: sqlite3.Connection, rows: list[dict]) -> int:
    con.executemany(
        "INSERT INTO quotes VALUES (:ts,:T,:K,:iv_bid,:iv_ask,:mark_iv,:spot)",
        [{"ts": time.time(), **{k: r[k] for k in ("T", "K", "iv_bid", "iv_ask", "mark_iv", "spot")}}
         for r in rows],
    )
    con.commit()
    return len(rows)


def load_latest_snapshot(con: sqlite3.Connection, max_age_sec: float = 3600) -> list[dict]:
    cutoff = time.time() - max_age_sec
    cur = con.execute(
        "SELECT T,K,iv_bid,iv_ask FROM quotes WHERE ts > ? ORDER BY T, K", (cutoff,))
    return [{"T": t, "K": k, "iv_bid": b, "iv_ask": a} for t, k, b, a in cur.fetchall()]


def log_alert(con: sqlite3.Connection, kind: str, expiry_short: float,
              expiry_long: float, k_min: float, k_max: float,
              severity: float, quote_json: str = "{}") -> int:
    cur = con.execute(
        "INSERT INTO alerts (detected_at,kind,expiry_short,expiry_long,k_min,k_max,severity,quote_json)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (time.time(), kind, expiry_short, expiry_long, k_min, k_max, severity, quote_json))
    con.commit()
    return int(cur.lastrowid)


def resolve_alerts(con: sqlite3.Connection, older_than_sec: float = 86400) -> int:
    """Mark stale alerts resolved; persistence stats come from alert_stats."""
    cutoff = time.time() - older_than_sec
    cur = con.execute("UPDATE alerts SET resolved_at=? WHERE resolved_at IS NULL AND detected_at < ?",
                      (time.time(), cutoff))
    con.commit()
    return cur.rowcount


def alert_stats(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        "SELECT kind, COUNT(*), AVG(resolved_at IS NULL), AVG(severity) FROM alerts GROUP BY kind"
    ).fetchall()
    return {
        kind: {"count": n, "open_share": round(open_share, 3), "avg_severity": round(sev, 4)}
        for kind, n, open_share, sev in rows
    }
