#!/usr/bin/env python3
"""Build a resumable chan.py signal snapshot from the complete stock universe."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backtest.data import load_daily_bars
from app.config import settings
from app.database import execute_query
from app.strategy.chanpy_adapter import detect_chanpy_signals


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_code(value: object) -> str:
    return str(value or "").strip().upper().split(".", 1)[0]


def load_or_create_manifest(run_dir: Path, start_date: str, end_date: str) -> dict:
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    stocks = execute_query(
        "SELECT stock_code, stock_name FROM trade_stock_status "
        "WHERE stock_code IS NOT NULL AND stock_code <> '' ORDER BY stock_code"
    )
    stock_codes = sorted({normalize_code(row.get("stock_code")) for row in stocks if normalize_code(row.get("stock_code"))})
    manifest = {
        "run_id": run_dir.name,
        "engine": "chan.py",
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "start_date": start_date,
        "end_date": end_date,
        "stock_total": len(stock_codes),
        "stock_completed": 0,
        "stock_success": 0,
        "stock_failed": 0,
        "last_stock_code": None,
        "output_path": str((run_dir / "signals.jsonl").resolve()),
        "stocks": stock_codes,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def write_manifest(path: Path, manifest: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_status(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            result[row["stock_code"]] = row
    return result


def append_status(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        handle.flush()


def append_signals(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        handle.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=datetime.now().date().isoformat())
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = (settings.REBUILD_DIR / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_or_create_manifest(run_dir, args.start_date, args.end_date)
    status_path = run_dir / "stocks.jsonl"
    signal_path = run_dir / "signals.jsonl"
    statuses = load_status(status_path)
    pending = [code for code in manifest["stocks"] if statuses.get(code, {}).get("status") != "success"]
    if args.limit > 0:
        pending = pending[:args.limit]

    for code in pending:
        started = utc_now()
        try:
            frame = load_daily_bars(code, args.start_date, args.end_date, execute_query)
            signals = detect_chanpy_signals(frame, code, args.end_date)
            append_signals(signal_path, signals)
            row = {"stock_code": code, "status": "success", "signal_count": len(signals), "started_at": started, "finished_at": utc_now()}
            append_status(status_path, row)
            statuses[code] = row
        except Exception as exc:
            row = {"stock_code": code, "status": "failed", "signal_count": 0, "started_at": started, "finished_at": utc_now(), "error": f"{type(exc).__name__}: {exc}"}
            append_status(status_path, row)
            statuses[code] = row
        manifest.update({
            "stock_completed": sum(item.get("status") in {"success", "failed"} for item in statuses.values()),
            "stock_success": sum(item.get("status") == "success" for item in statuses.values()),
            "stock_failed": sum(item.get("status") == "failed" for item in statuses.values()),
            "last_stock_code": code,
        })
        write_manifest(run_dir / "manifest.json", manifest)

    complete = manifest["stock_completed"] == manifest["stock_total"]
    manifest.update({"status": "completed" if complete else "paused", "finished_at": utc_now() if complete else None})
    write_manifest(run_dir / "manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("run_id", "status", "stock_total", "stock_completed", "stock_success", "stock_failed", "output_path")}, ensure_ascii=False))
    return 0 if not manifest["stock_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
