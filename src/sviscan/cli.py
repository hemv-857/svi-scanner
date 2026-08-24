"""CLI: `sviscan scan` runs one detection cycle; `sviscan report` summarizes alerts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .scanner import build_slices, scan_surface
from .store import (
    alert_stats,
    fetch_chain,
    init_store,
    load_latest_snapshot,
    log_alert,
    resolve_alerts,
    save_quotes,
)


def _scan(args):
    quotes = fetch_chain(args.currency) if not args.offline else []
    con = init_store(args.db)
    if quotes:
        n = save_quotes(con, quotes)
        print(f"fetched {n} option quotes from Deribit ({args.currency})")
    else:
        quotes = load_latest_snapshot(con)
        print(f"offline: using {len(quotes)} cached quotes")

    slices = build_slices(quotes)
    print(f"built {len(slices)} expiry slices")
    alerts = scan_surface(slices, rmse_gate=args.gate)
    jsonl_path = Path(args.db).parent / "alerts.jsonl"
    with open(jsonl_path, "a") as jl:
        for a in alerts:
            aid = log_alert(con, a["kind"], a["T_short"] or 0.0, a["T_long"] or 0.0,
                            a["k_min"], a["k_max"], a["severity"])
            rec = {"id": aid, "detected_at": time.time(), **a}
            jl.write(json.dumps(rec) + "\n")
            print(f"[{aid}] {a['kind']}: T={a['T_long'] or a['T_short']:.3f} "
                  f"k=[{a['k_min']:.2f},{a['k_max']:.2f}] severity={a['severity']:.5f}")
    if not alerts:
        print("no violations detected")
    resolve_alerts(con, older_than_sec=7 * 86400)


def _report(args):
    con = init_store(args.db)
    print(json.dumps(alert_stats(con), indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sviscan", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="fetch chain, fit slices, detect arbs, log")
    s.add_argument("--currency", default="BTC")
    s.add_argument("--db", default="data/scanner.db")
    s.add_argument("--gate", type=float, default=0.004)
    s.add_argument("--offline", action="store_true", help="reuse latest cached snapshot")
    s.set_defaults(func=_scan)

    r = sub.add_parser("report", help="alert persistence stats")
    r.add_argument("--db", default="data/scanner.db")
    r.set_defaults(func=_report)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
