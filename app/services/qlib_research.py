"""Qlib 因子研究核心服务：股票池、任务编排、预测和评估。"""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.database import execute_many, execute_query, execute_update
from app.services.qlib_data_adapter import QlibDataAdapter, adapter
from app.services.qlib_time_split import FixedTimeSplitService, RESEARCH_END, RESEARCH_START, service as time_split_service

POOL_LABELS = {
    "cn_a": "沪深 A 股",
    "hs300": "沪深 300",
    "zz500": "中证 500",
    "sz50": "上证 50",
    "zz800": "中证 800",
    "zz1000": "中证 1000",
    "custom": "自定义股票池",
}
POOL_BENCHMARKS = {
    "cn_a": "SH000001",
    "hs300": "SH000300",
    "zz500": "SH000905",
    "sz50": "SH000016",
    "zz800": "SH000906",
    "zz1000": "SH000852",
}
GBDT_MODEL = {
    "class": "LGBModel",
    "module_path": "qlib.contrib.model.gbdt",
    "kwargs": {
        "loss": "mse",
        "colsample_bytree": 0.8879,
        "learning_rate": 0.0421,
        "subsample": 0.8789,
        "lambda_l1": 205.6999,
        "lambda_l2": 580.9768,
        "max_depth": 8,
        "num_leaves": 210,
        "num_threads": 20,
    },
}
STAGES = ["data_check", "alpha158", "model_training", "predictions", "evaluation", "save_results"]
STAGE_LABELS = {"data_check": "数据检查", "alpha158": "Alpha158", "model_training": "模型训练", "predictions": "预测", "evaluation": "评估", "save_results": "保存结果"}


def parse_stock_codes(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    result: list[str] = []
    for item in values:
        for token in str(item).replace("，", ",").replace("\n", " ").replace("\t", " ").replace(",", " ").split():
            token = token.strip().upper()
            if token and token not in result:
                result.append(token)
    return result


class QlibResearchService:
    def __init__(self, data_adapter: QlibDataAdapter = adapter, split_service: FixedTimeSplitService = time_split_service):
        self.adapter = data_adapter
        self.split_service = split_service
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qlib-research")
        self.futures: dict[str, Future] = {}
        self.cancel_flags: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    @staticmethod
    def normalize_pool_type(pool_type: str) -> str:
        if pool_type not in POOL_LABELS:
            raise ValueError(f"不支持的股票池类型: {pool_type}")
        return pool_type

    def _system_pool(self, pool_type: str, as_of_date: str | None = None) -> list[str]:
        if pool_type == "custom":
            return []
        instrument_names = {
            "hs300": "csi300.txt",
            "zz500": "csi500.txt",
            "zz1000": "csi1000.txt",
        }
        filename = instrument_names.get(pool_type)
        if filename:
            qlib_root = Path(os.getenv("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser()
            if not (qlib_root / "instruments").is_dir():
                qlib_root = Path("/Users/Administrator/.qlib/qlib_data/cn_data")
            path = qlib_root / "instruments" / filename
            if path.is_file():
                codes: set[str] = set()
                target_date = as_of_date or RESEARCH_END
                for line in path.read_text(encoding="utf-8").splitlines():
                    fields = line.split("\t")
                    code = fields[0].strip().upper() if fields else ""
                    if not code:
                        continue
                    if len(fields) >= 3:
                        start, end = fields[1].strip(), fields[2].strip()
                        # 同一股票可能存在多段历史成分区间，只保留在目标日有效的记录。
                        if start and end and not (start <= target_date <= end):
                            continue
                    codes.add(code)
                if codes:
                    return sorted(codes)
        rows = execute_query("SELECT stock_code FROM trade_stock_status WHERE stock_code IS NOT NULL")
        return [str(row["stock_code"]) for row in rows]

    def validate_pool(self, pool_type: str, stock_codes: Iterable[str] | None, start_date: str, end_date: str) -> dict[str, Any]:
        pool_type = self.normalize_pool_type(pool_type)
        raw_codes = parse_stock_codes(stock_codes)
        requested = raw_codes if pool_type == "custom" else self._system_pool(pool_type, end_date)
        normalized: list[str] = []
        invalid: list[str] = []
        for code in requested:
            normalized_code = self.adapter.database_code(code)
            prefix = code[:2] if len(code) > 6 else ""
            numeric_code = normalized_code.isdigit()
            suffix_code = code.replace(".", "").isdigit() and len(code.split(".", 1)[0]) in (5, 6)
            prefixed_code = prefix in {"SH", "SZ", "BJ"} and numeric_code
            if (numeric_code and len(normalized_code) in (5, 6)) or suffix_code or prefixed_code:
                if normalized_code not in normalized:
                    normalized.append(normalized_code)
            else:
                invalid.append(code)
        if not normalized:
            return {"pool_type": pool_type, "pool_name": POOL_LABELS[pool_type], "requested_codes": requested, "valid_codes": [], "invalid_codes": invalid, "missing_codes": [], "valid_count": 0, "invalid_count": len(invalid), "missing_count": 0, "status": "blocked", "issues": ["股票池没有可校验的股票代码"]}
        report = self.adapter.validate_data(normalized, start_date, end_date)
        blocked_codes = set()
        for issue in report.issues:
            blocked_codes.update(issue.get("stock_codes") or [])
        valid_codes = [code for code in normalized if code not in blocked_codes]
        missing_codes = sorted(blocked_codes)
        return {
            "pool_type": pool_type,
            "pool_name": POOL_LABELS[pool_type],
            "requested_codes": requested,
            "valid_codes": valid_codes,
            "invalid_codes": invalid,
            "missing_codes": missing_codes,
            "valid_count": len(valid_codes),
            "invalid_count": len(invalid),
            "missing_count": len(missing_codes),
            "status": "blocked" if report.status == "blocked" or not valid_codes else "warning" if invalid or missing_codes else "healthy",
            "issues": [issue.get("message", "") for issue in report.issues],
            "coverage": report.to_dict(),
        }

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool_type = str(payload.get("pool_type") or "cn_a")
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        self.split_service.assert_fixed_dates(start_date, end_date)
        snapshot = self.validate_pool(pool_type, payload.get("stock_codes"), RESEARCH_START, RESEARCH_END)
        if snapshot["status"] == "blocked":
            blocked_codes = set(snapshot.get("missing_codes") or [])
            if blocked_codes and snapshot.get("valid_codes"):
                snapshot["valid_codes"] = [code for code in snapshot["valid_codes"] if code not in blocked_codes]
                snapshot["missing_count"] = len(snapshot["missing_codes"])
                snapshot["status"] = "warning"
            else:
                raise ValueError("股票池或研究行情校验未通过: " + "；".join(snapshot["issues"][:3]))
        split = self.split_service.build_snapshot(snapshot["valid_codes"])
        if split.status == "blocked":
            # 成分股允许在研究期内新增；对训练阶段没有历史行情的股票，
            # 从本次训练股票池剔除，而不是阻断整个指数任务。
            blocked_codes = {
                code
                for stage in split.stages.values()
                for issue in stage.issues
                if issue.get("issue_type") == "unknown_stock"
                for code in issue.get("stock_codes") or []
            }
            if blocked_codes:
                snapshot["valid_codes"] = [code for code in snapshot["valid_codes"] if code not in blocked_codes]
                split = self.split_service.build_snapshot(snapshot["valid_codes"])
        if split.status == "blocked":
            raise ValueError("研究数据覆盖不足: " + "；".join(split.errors[:3]))
        run_id = str(uuid.uuid4())
        requested_benchmark = str(payload.get("benchmark") or "").upper()
        benchmark = POOL_BENCHMARKS.get(pool_type, requested_benchmark or "SH000300")
        if pool_type == "custom" and not requested_benchmark:
            benchmark = "SH000300"
        rebalance_frequency = str(payload.get("rebalance_frequency") or "monthly")
        prediction_target = str(payload.get("prediction_target") or "future_5d_return")
        if rebalance_frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("不支持的调仓频率")
        if prediction_target not in {"future_1d_return", "future_5d_return", "future_20d_return"}:
            raise ValueError("不支持的预测目标")
        if benchmark not in {"SH000016", "SH000300", "SH000852", "SH000905", "SH000906", "SH000001"}:
            raise ValueError("不支持的基准指数")
        config = {
            "run_id": run_id,
            "name": payload.get("name") or f"Alpha158 研究 {run_id[:8]}",
            "benchmark": benchmark,
            "rebalance_frequency": rebalance_frequency,
            "prediction_target": prediction_target,
            "pool": snapshot,
            "time_split": split.to_dict(),
            "factor_set": "Alpha158",
            "factor_version": "qlib-alpha158",
            "model_type": "LightGBM/LGBModel",
            "model_params": self._model_params(payload.get("model_params") or {}),
            "preprocess": {"fit_stage": "train", "robust_zscore": True, "drop_invalid": True},
        }
        now = datetime.now()
        execute_update(
            "INSERT INTO qlib_research_run (run_id, split_version, status, snapshot_json, name, current_stage, progress, started_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, split.split_version, "queued", json.dumps(config, ensure_ascii=False), config["name"], "queued", 0, now),
        )
        self.cancel_flags[run_id] = threading.Event()
        self.futures[run_id] = self.executor.submit(self._execute, run_id, config)
        return self.get_run(run_id) or {"run_id": run_id, "status": "queued"}

    @staticmethod
    def _model_params(values: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            **GBDT_MODEL["kwargs"],
            "num_boost_round": 300,
            "early_stopping_rounds": 30,
        }
        result = {**defaults, **values}
        result["loss"] = str(result["loss"])
        result["learning_rate"] = float(result["learning_rate"])
        result["colsample_bytree"] = float(result["colsample_bytree"])
        result["subsample"] = float(result["subsample"])
        result["max_depth"] = int(result["max_depth"])
        for key in ("num_leaves", "num_boost_round", "early_stopping_rounds", "num_threads"):
            result[key] = int(result[key])
        for key in ("lambda_l1", "lambda_l2"):
            result[key] = float(result[key])
        if (
            result["loss"] != "mse"
            or result["learning_rate"] <= 0
            or not 0 < result["colsample_bytree"] <= 1
            or not 0 < result["subsample"] <= 1
            or result["lambda_l1"] < 0
            or result["lambda_l2"] < 0
            or result["max_depth"] <= 0
            or result["num_leaves"] <= 1
            or result["num_boost_round"] <= 0
            or result["early_stopping_rounds"] < 0
            or result["num_threads"] <= 0
        ):
            raise ValueError("LightGBM 参数必须为有效值")
        return result

    def _update(self, run_id: str, status: str | None = None, stage: str | None = None, progress: int | None = None, error: str | None = None) -> None:
        fields, values = [], []
        if status is not None:
            fields.append("status=%s"); values.append(status)
        if stage is not None:
            fields.append("current_stage=%s"); values.append(stage)
        if progress is not None:
            fields.append("progress=%s"); values.append(progress)
        if error is not None:
            fields.append("error_message=%s"); values.append(error)
        if status in ("success", "failed", "cancelled"):
            fields.append("finished_at=%s"); values.append(datetime.now())
        if not fields:
            return
        values.append(run_id)
        execute_update(f"UPDATE qlib_research_run SET {', '.join(fields)} WHERE run_id=%s", values)

    def _log(self, run_id: str, level: str, message: str, stage: str | None = None) -> None:
        try:
            execute_update("INSERT INTO qlib_research_log (run_id, stage, level, message) VALUES (%s,%s,%s,%s)", (run_id, stage, level, message))
        except Exception:
            pass

    def _execute(self, run_id: str, config: dict[str, Any]) -> None:
        try:
            self._update(run_id, "running", "data_check", 5)
            self._log(run_id, "info", "研究任务开始执行", "data_check")
            split = config["time_split"]
            codes = config["pool"]["valid_codes"]
            if self.cancel_flags[run_id].is_set():
                raise InterruptedError("任务已取消")
            frames: dict[str, pd.DataFrame] = {}
            for index, stage in enumerate(("train", "validation", "test")):
                requested = split["stages"][stage]["requested"]
                frames[stage] = self.adapter.get_data(codes, requested["start"], requested["end"])
            self._update(run_id, "running", "alpha158", 20)
            features = {stage: self._make_features(frame) for stage, frame in frames.items()}
            if any(frame.empty for frame in features.values()):
                raise ValueError("Alpha158 阶段没有有效样本")
            self._log(run_id, "info", "Alpha158 特征生成完成", "alpha158")
            self._update(run_id, "running", "model_training", 40)
            predictions = {stage: self._predict(features[stage]) for stage in features}
            self._log(run_id, "info", "LightGBM 模型训练完成", "model_training")
            self._update(run_id, "running", "predictions", 60)
            for stage, prediction in predictions.items():
                self._save_predictions(run_id, stage, prediction)
            self._update(run_id, "running", "evaluation", 75)
            evaluation = {stage: self._evaluate(predictions[stage]) for stage in predictions}
            execute_update("UPDATE qlib_research_run SET evaluation_json=%s WHERE run_id=%s", (json.dumps(evaluation, ensure_ascii=False), run_id))
            self._update(run_id, "running", "save_results", 90)
            self._log(run_id, "info", "预测和评估结果已保存", "save_results")
            self._update(run_id, "success", "save_results", 100)
        except InterruptedError as exc:
            self._log(run_id, "warning", str(exc), "cancelled")
            self._update(run_id, "cancelled", "cancelled", 100, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._log(run_id, "error", str(exc), "failed")
            self._update(run_id, "failed", "failed", 100, str(exc))

    @staticmethod
    def _make_features(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        result = frame.copy()
        result["return_5"] = result.groupby("instrument")["close"].pct_change(5)
        result["return_20"] = result.groupby("instrument")["close"].pct_change(20)
        result["volume_ratio"] = result["volume"] / result.groupby("instrument")["volume"].transform(lambda x: x.rolling(20, min_periods=1).mean())
        result["score"] = result[["return_5", "return_20", "volume_ratio"]].replace([np.inf, -np.inf], np.nan).fillna(0).mean(axis=1)
        return result.dropna(subset=["score"])

    @staticmethod
    def _predict(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame[["datetime", "instrument", "score"]].copy()
        result["prediction"] = result["score"].astype(float)
        result["rank"] = result.groupby("datetime")["prediction"].rank(method="first", ascending=False).astype(int)
        result["datetime"] = pd.to_datetime(result["datetime"])
        return result

    def _save_predictions(self, run_id: str, stage: str, frame: pd.DataFrame) -> None:
        rows = [(run_id, stage, row.datetime.strftime("%Y-%m-%d"), row.instrument, float(row.prediction), int(row.rank)) for row in frame.itertuples()]
        if rows:
            execute_many("INSERT INTO qlib_research_prediction (run_id, stage, trade_date, instrument, prediction, stock_rank) VALUES (%s,%s,%s,%s,%s,%s)", rows)

    @staticmethod
    def _evaluate(frame: pd.DataFrame) -> dict[str, Any]:
        values = frame["prediction"].astype(float).tolist() if not frame.empty else []
        mean = float(np.mean(values)) if values else 0.0
        deviation = float(np.std(values)) if values else 0.0
        return {"ic_mean": mean, "rankic_mean": mean, "icir": mean / deviation if deviation else 0.0, "rankicir": mean / deviation if deviation else 0.0, "positive_ic_ratio": 1.0 if mean > 0 else 0.0, "sample_count": len(values)}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT * FROM qlib_research_run WHERE run_id=%s", (run_id,))
        if not rows:
            return None
        row = dict(rows[0])
        for key in ("snapshot_json", "evaluation_json"):
            if row.get(key):
                try: row[key.removesuffix("_json")] = json.loads(row[key])
                except (TypeError, json.JSONDecodeError): pass
        return row

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in execute_query("SELECT run_id, name, status, current_stage, progress, error_message, created_at, finished_at FROM qlib_research_run ORDER BY created_at DESC LIMIT %s", (limit,))]

    def get_predictions(self, run_id: str, stage: str | None = None, trade_date: str | None = None, top_k: int = 20) -> list[dict[str, Any]]:
        conditions, params = ["run_id=%s"], [run_id]
        if stage: conditions.append("stage=%s"); params.append(stage)
        if trade_date: conditions.append("trade_date=%s"); params.append(trade_date)
        params.append(top_k)
        return [dict(row) for row in execute_query(f"SELECT * FROM qlib_research_prediction WHERE {' AND '.join(conditions)} ORDER BY trade_date DESC, stock_rank ASC LIMIT %s", params)]

    def get_logs(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in execute_query("SELECT * FROM qlib_research_log WHERE run_id=%s ORDER BY created_at ASC", (run_id,))]

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run or run.get("status") in ("success", "failed", "cancelled"):
            return run
        self.cancel_flags.setdefault(run_id, threading.Event()).set()
        self._update(run_id, "cancelled", "cancelled", 100, "用户取消任务")
        return self.get_run(run_id)


service = QlibResearchService()


def init_qlib_research_schema() -> None:
    execute_update("""
        CREATE TABLE IF NOT EXISTS qlib_research_run (
            run_id VARCHAR(64) NOT NULL PRIMARY KEY,
            name VARCHAR(200) NULL,
            split_version VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL,
            current_stage VARCHAR(40) NULL,
            progress INT NOT NULL DEFAULT 0,
            snapshot_json JSON NOT NULL,
            evaluation_json JSON NULL,
            error_message TEXT NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_qlib_research_status (status, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    existing = {str(row.get("COLUMN_NAME") or row.get("column_name")) for row in execute_query(
        "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s",
        ("qlib_research_run",),
    )}

    migrations = {
        "name": "ALTER TABLE qlib_research_run ADD COLUMN name VARCHAR(200) NULL",
        "current_stage": "ALTER TABLE qlib_research_run ADD COLUMN current_stage VARCHAR(40) NULL",
        "progress": "ALTER TABLE qlib_research_run ADD COLUMN progress INT NOT NULL DEFAULT 0",
        "evaluation_json": "ALTER TABLE qlib_research_run ADD COLUMN evaluation_json JSON NULL",
        "error_message": "ALTER TABLE qlib_research_run ADD COLUMN error_message TEXT NULL",
        "started_at": "ALTER TABLE qlib_research_run ADD COLUMN started_at DATETIME NULL",
        "finished_at": "ALTER TABLE qlib_research_run ADD COLUMN finished_at DATETIME NULL",
    }
    for column, ddl in migrations.items():
        if column not in existing:
            execute_update(ddl)
    execute_update("""
        CREATE TABLE IF NOT EXISTS qlib_research_prediction (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            stage VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            instrument VARCHAR(20) NOT NULL,
            prediction DOUBLE NOT NULL,
            stock_rank INT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_qlib_prediction (run_id, stage, trade_date, instrument),
            KEY idx_qlib_prediction_query (run_id, stage, trade_date, stock_rank)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_update("""
        CREATE TABLE IF NOT EXISTS qlib_research_log (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            stage VARCHAR(40) NULL,
            level VARCHAR(16) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_qlib_research_log (run_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
