"""ATR 季度滚动验证、盲测和版本决策。"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from .parameters import ParameterState
from .quarterly_repository import QuarterlyRepository
from .runner import scan_atr_exit_mult


@dataclass(frozen=True)
class EvaluationWindow:
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str


def generate_candidates(values: Iterable[float] | None = None, range_start: float | None = None,
                        range_end: float | None = None, step: float | None = None) -> list[float]:
    if values is not None:
        return sorted({float(Decimal(str(value))) for value in values})
    if None in (range_start, range_end, step) or step <= 0 or range_end < range_start:
        raise ValueError("候选参数必须提供有效 values 或 range_start/range_end/step")
    result, value = [], Decimal(str(range_start))
    end, increment = Decimal(str(range_end)), Decimal(str(step))
    while value <= end:
        result.append(float(value))
        value += increment
    return result


def fixed_baseline_window() -> EvaluationWindow:
    return EvaluationWindow("2022-01-01", "2024-06-30", "2024-07-01", "2025-03-31", "2025-04-01", "2025-12-31")


def rolling_window(evaluation_quarter: str, data_as_of: str, train_days: int = 730,
                   validation_days: int = 273, test_days: int = 273) -> EvaluationWindow:
    quarter_end = pd.Timestamp(data_as_of).normalize()
    test_end = quarter_end
    test_start = test_end - pd.Timedelta(days=test_days - 1)
    validation_end = test_start - pd.Timedelta(days=1)
    validation_start = validation_end - pd.Timedelta(days=validation_days - 1)
    train_end = validation_start - pd.Timedelta(days=1)
    train_start = train_end - pd.Timedelta(days=train_days - 1)
    return EvaluationWindow(*(str(value.date()) for value in (train_start, train_end, validation_start, validation_end, test_start, test_end)))


def _metrics(result) -> list[dict]:
    return result.summary.to_dict("records") if hasattr(result.summary, "to_dict") else list(result.summary)


def _aggregate(rows: list[dict], multiplier: float) -> dict:
    selected = [row for row in rows if float(row.get("atr_exit_mult", multiplier)) == multiplier]
    if not selected:
        return {"atr_exit_mult": multiplier, "trade_count": 0, "stock_count": 0, "industry_count": 0, "max_drawdown": None, "total_return": None}
    def mean(key):
        values = [float(row[key]) for row in selected if row.get(key) is not None]
        return sum(values) / len(values) if values else None
    return {"atr_exit_mult": multiplier, "trade_count": int(sum(int(row.get("trade_count", 0) or 0) for row in selected)),
            "stock_count": len({row.get("stock_code") for row in selected if row.get("stock_code")}),
            "industry_count": len({row.get("industry") for row in selected if row.get("industry")}),
            "total_return": mean("total_return"), "annualized_return": mean("annualized_return"),
            "max_drawdown": mean("max_drawdown"), "sharpe_ratio": mean("sharpe_ratio"), "calmar_ratio": mean("calmar_ratio"),
            "concentration_risk": bool(any(row.get("concentration_risk", False) for row in selected))}


def _run_stage(data_by_stock: dict, stock_codes: Iterable[str], start: str, end: str, candidates: list[float], config, adapter, runner: Callable = scan_atr_exit_mult) -> list[dict]:
    rows = []
    for code in sorted(set(stock_codes)):
        frame = data_by_stock.get(code)
        if frame is None or frame.empty:
            continue
        try:
            result = runner(stock_code=code, start_date=start, end_date=end, multipliers=candidates, config=config, adapter=adapter, data=frame, evaluate_periods=False)
            for row in _metrics(result):
                row["stock_code"] = code
                rows.append(row)
        except Exception:
            continue
    return rows


def _select(train: list[dict], validation: list[dict], candidates: list[float], current: ParameterState, min_trades: int = 10,
            min_stocks: int = 1, max_drawdown: float = 1.0) -> tuple[dict | None, list[dict]]:
    train_rows = [_aggregate(train, value) for value in candidates]
    valid_rows = [_aggregate(validation, value) for value in candidates]
    eligible = []
    for train_row, valid_row in zip(train_rows, valid_rows):
        if train_row["trade_count"] < min_trades or valid_row["trade_count"] < min_trades:
            continue
        if train_row["stock_count"] < min_stocks or valid_row["stock_count"] < min_stocks:
            continue
        if any(row.get("max_drawdown") is not None and float(row["max_drawdown"]) < -abs(max_drawdown) for row in (train_row, valid_row)):
            continue
        if train_row["concentration_risk"] or valid_row["concentration_risk"]:
            continue
        score = float(valid_row.get("calmar_ratio") or -999) + float(valid_row.get("sharpe_ratio") or -999)
        eligible.append((score, train_row, valid_row))
    if not eligible:
        return None, valid_rows
    eligible.sort(key=lambda item: item[0], reverse=True)
    best = eligible[0]
    neighbor = [item for item in eligible if abs(item[1]["atr_exit_mult"] - best[1]["atr_exit_mult"]) <= 0.5]
    chosen = sorted(neighbor, key=lambda item: item[1]["atr_exit_mult"])[len(neighbor) // 2]
    row = chosen[2].copy()
    row["train"] = chosen[1]
    row["validation"] = chosen[2]
    row["stability_interval"] = [item[1]["atr_exit_mult"] for item in neighbor]
    row["improves_current"] = row["atr_exit_mult"] != current.atr_exit_mult
    return row, valid_rows


class QuarterlyParameterService:
    def __init__(self, repository: QuarterlyRepository | None = None, output_dir: str = "data/backtest/quarterly"):
        self.repository = repository
        self.output_dir = Path(output_dir)

    @staticmethod
    def _write_comparison(rows: list[dict], target: Path) -> None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            target.touch()
            return
        frame = pd.DataFrame(rows)
        figure, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        if not frame.empty:
            axes[0].bar(frame["atr_exit_mult"].astype(str), frame["total_return"].fillna(0))
            axes[1].bar(frame["atr_exit_mult"].astype(str), frame["max_drawdown"].fillna(0))
        axes[0].set_ylabel("Return")
        axes[1].set_ylabel("Drawdown")
        axes[1].set_xlabel("ATR exit multiplier")
        figure.tight_layout()
        figure.savefig(target, dpi=150)
        plt.close(figure)

    def run(self, data_by_stock: dict, stock_codes: Iterable[str], current: ParameterState,
            evaluation_quarter: str, data_as_of: str, candidates: Iterable[float] | None = None,
            range_start: float | None = None, range_end: float | None = None, step: float | None = None,
            config=None, adapter=None, baseline: bool = False, effective_date: str | None = None,
            runner: Callable = scan_atr_exit_mult) -> dict:
        values = generate_candidates(candidates, range_start, range_end, step)
        window = fixed_baseline_window() if baseline else rolling_window(evaluation_quarter, data_as_of)
        if pd.Timestamp(data_as_of) < pd.Timestamp(window.test_end):
            blocked = {"status": "blocked", "reason": "data_incomplete", "evaluation_quarter": evaluation_quarter, "data_as_of": data_as_of, "required_test_end": window.test_end}
            if self.repository:
                self.repository.start_run({"run_id": f"atr-{evaluation_quarter}-blocked-{uuid.uuid4().hex[:8]}", "strategy_name": "atr_chan", "evaluation_quarter": evaluation_quarter, "data_as_of": data_as_of, "run_mode": "baseline" if baseline else "rolling", **asdict(window)})
            return blocked
        if not data_by_stock:
            return {"status": "blocked", "reason": "data_incomplete", "missing": "stock_pool"}
        if adapter is None:
            raise ValueError("季度验证必须显式提供策略 adapter；请使用内部 StrategyAdapter 或注入 runner 进行测试")
        for code, frame in data_by_stock.items():
            if frame is None or frame.empty:
                continue
            if pd.Timestamp(frame.index.max()) > pd.Timestamp(data_as_of):
                raise ValueError(f"{code} contains data after data_as_of")
        run_id = f"atr-{evaluation_quarter}-{uuid.uuid4().hex[:10]}"
        context = {"run_id": run_id, "strategy_name": "atr_chan", "evaluation_quarter": evaluation_quarter, "data_as_of": data_as_of, "run_mode": "baseline" if baseline else "rolling", **asdict(window), "candidates": values}
        if self.repository:
            duplicate = self.repository.get_run(evaluation_quarter)
            if duplicate and duplicate.get("status") in {"started", "completed", "blocked"}:
                return {"status": "skipped_duplicate", "run_id": duplicate.get("run_id"), "existing": duplicate}
            self.repository.start_run(context)
        try:
            train = _run_stage(data_by_stock, stock_codes, window.train_start, window.train_end, values, config, adapter, runner)
            validation = _run_stage(data_by_stock, stock_codes, window.validation_start, window.validation_end, values, config, adapter, runner)
            selected, validation_summary = _select(train, validation, values, current)
            test_values = [selected["atr_exit_mult"]] if selected else []
            test = _run_stage(data_by_stock, stock_codes, window.test_start, window.test_end, test_values, config, adapter, runner)
            test_summary = _aggregate(test, test_values[0]) if test_values else None
            decision = {"decision": "keep_current", "old_multiplier": current.atr_exit_mult, "new_multiplier": current.atr_exit_mult, "reason": "没有通过季度训练和验证门槛", "risk_conclusion": "high"}
            version = None
            if selected and selected["improves_current"] and test_summary and test_summary["trade_count"] >= 10 and not test_summary["concentration_risk"]:
                version = {"parameter_version": f"atr-{evaluation_quarter}-v{datetime.now().strftime('%Y%m%d%H%M%S')}", "strategy_name": "atr_chan", "atr_period": current.atr_period, "atr_exit_mult": selected["atr_exit_mult"], "status": "validated", "evaluation_quarter": evaluation_quarter, "data_as_of": data_as_of, "effective_date": effective_date or data_as_of, "old_multiplier": current.atr_exit_mult, "new_multiplier": selected["atr_exit_mult"], "decision": "switch_to_new", "change_reason": "训练验证稳定，测试盲测通过", "risk_conclusion": "medium", "run_id": run_id, **asdict(window)}
                decision = {"decision": "switch_to_new", "old_multiplier": current.atr_exit_mult, "new_multiplier": selected["atr_exit_mult"], "reason": version["change_reason"], "risk_conclusion": version["risk_conclusion"]}
            report_dir = self.output_dir / evaluation_quarter / run_id
            report_dir.mkdir(parents=True, exist_ok=True)
            summary = {"run_id": run_id, **context, "current_parameter": current.atr_exit_mult, "validation": validation_summary, "selected": selected, "test": test_summary, "test_blind": True, "lookahead_risk": bool(adapter.lookahead_risk) if adapter else None, "decision": decision, "parameter_version": version}
            pd.DataFrame(validation_summary).to_csv(report_dir / "atr_quarterly_parameter_summary.csv", index=False)
            pd.DataFrame(test).to_csv(report_dir / "atr_quarterly_parameter_trades.csv", index=False)
            pd.DataFrame([test_summary] if test_summary else []).to_csv(report_dir / "atr_quarterly_parameter_equity.csv", index=False)
            pd.DataFrame(validation_summary).to_csv(report_dir / "atr_quarterly_parameter_stability.csv", index=False)
            self._write_comparison(validation_summary, report_dir / "atr_quarterly_parameter_comparison.png")
            (report_dir / "atr_quarterly_parameter_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            result = {"status": "completed", **summary, "report_dir": str(report_dir)}
            if version and self.repository:
                self.repository.save_version(version)
                self.repository.activate_version(version, current.atr_exit_mult)
            if self.repository:
                for stage, rows in (("train", train), ("validation", validation), ("test", test)):
                    for row in rows:
                        self.repository.save_result(run_id, stage, row)
                self.repository.save_decision(run_id, decision)
                for path in report_dir.iterdir():
                    self.repository.save_report(run_id, path.name, str(path))
                self.repository.finish_run(run_id, "completed", result)
            return result
        except Exception as exc:
            if self.repository:
                self.repository.finish_run(run_id, "failed", error=str(exc))
            raise
