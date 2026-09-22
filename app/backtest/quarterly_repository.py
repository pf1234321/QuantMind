"""ATR 季度验证的数据库仓储。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.database import execute_query, execute_update


class QuarterlyRepository:
    def __init__(self, query_fn=execute_query, update_fn=execute_update):
        self.query_fn = query_fn
        self.update_fn = update_fn

    def get_run(self, evaluation_quarter: str) -> dict | None:
        rows = self.query_fn(
            "SELECT * FROM atr_quarterly_run WHERE evaluation_quarter=%s ORDER BY id DESC LIMIT 1",
            (evaluation_quarter,),
        )
        return rows[0] if rows else None

    def start_run(self, context: dict) -> int:
        return self.update_fn(
            "INSERT INTO atr_quarterly_run (run_id, strategy_name, evaluation_quarter, data_as_of, "
            "train_start, train_end, validation_start, validation_end, test_start, test_end, run_mode, "
            "status, context_json, started_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (context["run_id"], context["strategy_name"], context["evaluation_quarter"], context["data_as_of"],
             context["train_start"], context["train_end"], context["validation_start"], context["validation_end"],
             context["test_start"], context["test_end"], context["run_mode"], "started",
             json.dumps(context, ensure_ascii=False, default=str), datetime.now()),
        )

    def finish_run(self, run_id: str, status: str, message: dict | None = None, error: str | None = None) -> None:
        self.update_fn(
            "UPDATE atr_quarterly_run SET status=%s, message_json=%s, error_text=%s, finished_at=%s WHERE run_id=%s",
            (status, json.dumps(message or {}, ensure_ascii=False, default=str), error, datetime.now(), run_id),
        )

    def save_result(self, run_id: str, stage: str, row: dict) -> None:
        self.update_fn(
            "INSERT INTO atr_quarterly_result (run_id, stage, atr_exit_mult, metrics_json, test_blind) VALUES (%s,%s,%s,%s,%s)",
            (run_id, stage, float(row["atr_exit_mult"]), json.dumps(row, ensure_ascii=False, default=str), int(stage == "test")),
        )

    def save_decision(self, run_id: str, decision: dict) -> None:
        self.update_fn(
            "INSERT INTO atr_quarterly_decision (run_id, decision, current_multiplier, new_multiplier, reason, risk_conclusion, details_json) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (run_id, decision["decision"], decision.get("old_multiplier"), decision.get("new_multiplier"),
             decision.get("reason"), decision.get("risk_conclusion"), json.dumps(decision, ensure_ascii=False, default=str)),
        )

    def save_version(self, version: dict) -> None:
        self.update_fn(
            "INSERT INTO atr_parameter_version (parameter_version, strategy_name, atr_period, atr_exit_mult, status, "
            "evaluation_quarter, train_start, train_end, validation_start, validation_end, test_start, test_end, data_as_of, effective_date, old_multiplier, new_multiplier, decision, change_reason, risk_conclusion, run_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (version["parameter_version"], version["strategy_name"], version["atr_period"], version["atr_exit_mult"],
            version["status"], version["evaluation_quarter"], version.get("train_start"), version.get("train_end"), version.get("validation_start"), version.get("validation_end"), version.get("test_start"), version.get("test_end"), version["data_as_of"], version.get("effective_date"),
             version.get("old_multiplier"), version.get("new_multiplier"), version["decision"], version.get("change_reason"),
             version.get("risk_conclusion"), version["run_id"]),
        )

    def activate_version(self, version: dict, old_multiplier: float | None) -> None:
        self.update_fn(
            "UPDATE atr_parameter_version SET status='superseded' WHERE strategy_name=%s AND status='active' AND atr_exit_mult<>%s",
            (version["strategy_name"], version["atr_exit_mult"]),
        )
        self.update_fn(
            "UPDATE atr_parameter_version SET status='active' WHERE parameter_version=%s",
            (version["parameter_version"],),
        )

    def current(self, strategy_name: str = "atr_chan") -> dict | None:
        rows = self.query_fn("SELECT * FROM atr_parameter_version WHERE strategy_name=%s AND status='active' ORDER BY effective_date DESC, id DESC LIMIT 1", (strategy_name,))
        return rows[0] if rows else None

    def history(self, strategy_name: str = "atr_chan", limit: int = 50) -> list[dict]:
        return self.query_fn("SELECT * FROM atr_parameter_version WHERE strategy_name=%s ORDER BY created_at DESC, id DESC LIMIT %s", (strategy_name, limit))

    def version(self, parameter_version: str) -> dict | None:
        rows = self.query_fn("SELECT * FROM atr_parameter_version WHERE parameter_version=%s LIMIT 1", (parameter_version,))
        return rows[0] if rows else None

    def reports(self, evaluation_quarter: str | None = None, run_id: str | None = None) -> list[dict]:
        if run_id:
            return self.query_fn("SELECT * FROM atr_quarterly_report WHERE run_id=%s ORDER BY id", (run_id,))
        if evaluation_quarter:
            return self.query_fn("SELECT r.* FROM atr_quarterly_report r JOIN atr_quarterly_run q ON q.run_id=r.run_id WHERE q.evaluation_quarter=%s ORDER BY r.created_at DESC", (evaluation_quarter,))
        return self.query_fn("SELECT * FROM atr_quarterly_report ORDER BY created_at DESC LIMIT 50")

    def save_report(self, run_id: str, report_type: str, path: str) -> None:
        self.update_fn("INSERT INTO atr_quarterly_report (run_id, report_type, file_path) VALUES (%s,%s,%s)", (run_id, report_type, path))
