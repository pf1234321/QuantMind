"""缠论信号持久化服务：线上使用 MySQL，显式传入路径时兼容 JSONL。"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import get_connection

SIGNAL_KEY = ("stock_code", "signal_type", "signal_date", "signal_level", "strategy_name")


def _signal_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("signal_date") or ""), str(row.get("confirmed_date") or ""), str(row.get("signal_type") or ""))


def init_chan_signal_schema() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chan_signals (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    stock_code VARCHAR(32) NOT NULL,
                    signal_type VARCHAR(32) NOT NULL,
                    signal_date VARCHAR(32) NOT NULL,
                    signal_level VARCHAR(32) NOT NULL DEFAULT 'daily',
                    strategy_name VARCHAR(64) NOT NULL DEFAULT 'chan.py',
                    engine VARCHAR(64) NULL,
                    chan_type VARCHAR(32) NULL,
                    signal_price DECIMAL(20,8) NULL,
                    confirmed_date VARCHAR(32) NULL,
                    pivot_date VARCHAR(32) NULL,
                    signal_status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
                    lookahead_risk TINYINT(1) NOT NULL DEFAULT 0,
                    payload_json LONGTEXT NULL,
                    created_at DATETIME(6) NOT NULL,
                    updated_at DATETIME(6) NOT NULL,
                    UNIQUE KEY uq_chan_signal (stock_code, signal_type, signal_date, signal_level, strategy_name),
                    KEY idx_chan_stock_date (stock_code, signal_date),
                    KEY idx_chan_type_date (signal_type, signal_date),
                    KEY idx_chan_status_date (signal_status, signal_date),
                    KEY idx_chan_strategy_date (strategy_name, signal_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        conn.commit()
    finally:
        conn.close()


class SignalStore:
    """Signal repository. Default instances use MySQL; a path enables JSONL compatibility."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            init_chan_signal_schema()

    @property
    def _file_mode(self) -> bool:
        return self.path is not None

    def _read(self) -> list[dict[str, Any]]:
        if not self.path or not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _item(signal: dict[str, Any]) -> dict[str, Any]:
        return {"strategy_name": signal.get("engine", "chan.py"), "signal_status": "confirmed", **signal}

    def upsert(self, signal: dict[str, Any]) -> dict[str, Any]:
        return self.upsert_many([signal])[0]

    def upsert_many(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not signals:
            return []
        items = [self._item(signal) for signal in signals]
        if self._file_mode:
            rows = self._read()
            indexes = {tuple(row.get(name) for name in SIGNAL_KEY): index for index, row in enumerate(rows)}
            saved = []
            for item in items:
                key = tuple(item.get(name) for name in SIGNAL_KEY)
                index = indexes.get(key)
                if index is None:
                    indexes[key] = len(rows)
                    rows.append(item)
                    saved.append(item)
                else:
                    rows[index].update(item)
                    saved.append(rows[index])
            self._write(rows)
            return saved

        now = datetime.now()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for item in items:
                    cur.execute(
                        """
                        INSERT INTO chan_signals
                        (stock_code, signal_type, signal_date, signal_level, strategy_name,
                         engine, chan_type, signal_price, confirmed_date, pivot_date,
                         signal_status, lookahead_risk, payload_json, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                         engine=VALUES(engine), chan_type=VALUES(chan_type), signal_price=VALUES(signal_price),
                         confirmed_date=VALUES(confirmed_date), pivot_date=VALUES(pivot_date),
                         signal_status=VALUES(signal_status), lookahead_risk=VALUES(lookahead_risk),
                         payload_json=VALUES(payload_json), updated_at=VALUES(updated_at)
                        """,
                        (
                            item.get("stock_code", ""), item.get("signal_type", ""), item.get("signal_date", ""),
                            item.get("signal_level", "daily"), item.get("strategy_name", "chan.py"),
                            item.get("engine"), item.get("chan_type"), item.get("signal_price"),
                            item.get("confirmed_date"), item.get("pivot_date"), item.get("signal_status", "confirmed"),
                            int(bool(item.get("lookahead_risk", False))), json.dumps(item, ensure_ascii=False, default=str), now, now,
                        ),
                    )
            conn.commit()
            return items
        finally:
            conn.close()

    def list(self, stock_code: str | None = None, signal_type: str | list[str] | None = None,
             latest_only: bool = False) -> list[dict[str, Any]]:
        signal_types = {signal_type} if isinstance(signal_type, str) else set(signal_type or [])
        if self._file_mode:
            rows = self._read()
            rows = [row for row in rows if (not stock_code or row.get("stock_code") == stock_code)
                    and (not signal_types or row.get("signal_type") in signal_types)]
        else:
            clauses = []
            params: list[Any] = []
            if stock_code:
                clauses.append("stock_code=%s"); params.append(stock_code)
            if signal_types:
                clauses.append("signal_type IN (" + ",".join(["%s"] * len(signal_types)) + ")"); params.extend(sorted(signal_types))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload_json FROM chan_signals" + where + " ORDER BY signal_date DESC, confirmed_date DESC, signal_type DESC", params)
                    rows = [json.loads(row["payload_json"]) for row in cur.fetchall()]
            finally:
                conn.close()
        if latest_only:
            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                code = str(row.get("stock_code") or "")
                if code and (code not in latest or _signal_sort_key(row) > _signal_sort_key(latest[code])):
                    latest[code] = row
            rows = list(latest.values())
        return sorted(rows, key=_signal_sort_key, reverse=True)

    def compact(self) -> int:
        if self._file_mode:
            rows = self._read()
            unique: dict[tuple[Any, ...], dict[str, Any]] = {}
            priority = {"third_sell": 5, "third_buy": 4, "second_sell": 3, "second_buy": 2, "first_sell": 1, "first_buy": 1}
            for row in rows:
                key = tuple(row.get(name) for name in SIGNAL_KEY)
                current = unique.get(key)
                if current is None or priority.get(str(row.get("signal_type")), 0) >= priority.get(str(current.get("signal_type")), 0):
                    unique[key] = row
            compacted = sorted(unique.values(), key=_signal_sort_key)
            if compacted != rows:
                self._write(compacted)
            return len(rows) - len(compacted)
        init_chan_signal_schema()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS count FROM chan_signals")
                return 0
        finally:
            conn.close()

    def migrate_jsonl(self, path: str | Path | None = None) -> int:
        source = Path(path or settings.SIGNAL_STORE_PATH).expanduser().resolve()
        if not source.exists():
            return 0
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        for start in range(0, len(rows), 1000):
            self.upsert_many(rows[start:start + 1000])
        return len(rows)

    def _write(self, rows: list[dict[str, Any]]) -> None:
        if not self.path:
            raise RuntimeError("MySQL SignalStore 不支持直接写 JSONL")
        temp_path = self.path.with_name(f".{self.path.name}.tmp")
        temp_path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8")
        temp_path.replace(self.path)
