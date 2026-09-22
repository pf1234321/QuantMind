"""Qlib 因子研究固定时间区间与阶段隔离。"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.database import execute_query, execute_update
from app.services.qlib_data_adapter import QlibDataAdapter, adapter

RESEARCH_START = "2022-01-04"
DEFAULT_QLIB_DIR = Path(os.getenv("QLIB_DATA_DIR", "~/.qlib/qlib_data/cn_data")).expanduser()


def _detect_local_qlib_last_date(data_dir: Path = DEFAULT_QLIB_DIR) -> str:
    """从本地 Qlib 日历读取最后完整交易日。"""
    calendar_path = data_dir / "calendars" / "day.txt"
    if not calendar_path.is_file():
        raise FileNotFoundError(f"本地 Qlib 交易日历不存在：{calendar_path}")
    values = []
    for line in calendar_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = line.strip()[:10]
        try:
            values.append(date.fromisoformat(value))
        except ValueError:
            continue
    if not values:
        raise ValueError(f"本地 Qlib 交易日历为空：{calendar_path}")
    return max(values).isoformat()


RESEARCH_END = os.getenv("QLIB_END_DATE") or _detect_local_qlib_last_date()
SPLIT_VERSION = f"local-qlib-{RESEARCH_END}-v1"


@dataclass(frozen=True)
class DateRange:
    start: str
    end: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class StageCoverage:
    requested: DateRange
    actual_start: str | None
    actual_end: str | None
    row_count: int
    stock_count: int
    trade_date_count: int
    status: str
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["requested"] = self.requested.to_dict()
        return result


@dataclass
class TimeSplitSnapshot:
    split_version: str
    research: DateRange
    stages: dict[str, StageCoverage]
    stock_codes: list[str]
    status: str
    errors: list[str] = field(default_factory=list)
    data_snapshot_id: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_version": self.split_version,
            "research": self.research.to_dict(),
            "stages": {name: stage.to_dict() for name, stage in self.stages.items()},
            "stock_codes": self.stock_codes,
            "status": self.status,
            "errors": self.errors,
            "data_snapshot_id": self.data_snapshot_id,
            "run_id": self.run_id,
            "editable": False,
        }


class FixedTimeSplitService:
    RESEARCH = DateRange(RESEARCH_START, RESEARCH_END)
    STAGES = {
        "train": DateRange("2022-01-04", "2024-12-31"),
        "validation": DateRange("2025-01-01", "2025-12-31"),
        "test": DateRange("2026-01-01", RESEARCH_END),
    }

    def __init__(self, data_adapter: QlibDataAdapter = adapter):
        self.adapter = data_adapter
        self.validate_configuration()

    @classmethod
    def validate_configuration(cls) -> None:
        parse = lambda value: date.fromisoformat(value)
        research_start, research_end = parse(cls.RESEARCH.start), parse(cls.RESEARCH.end)
        previous_end = None
        for name in ("train", "validation", "test"):
            current = cls.STAGES[name]
            start, end = parse(current.start), parse(current.end)
            if start > end or start < research_start or end > research_end:
                raise ValueError(f"{name} 区间不在研究范围内或开始日期晚于结束日期")
            if previous_end is not None and start <= previous_end:
                raise ValueError(f"{name} 区间与前一阶段重叠或未按时间递增")
            previous_end = end
        if cls.STAGES["train"].start != cls.RESEARCH.start or cls.STAGES["test"].end != cls.RESEARCH.end:
            raise ValueError("训练集和测试集边界必须覆盖完整研究范围")

    @classmethod
    def assert_fixed_dates(cls, start_date: str | None, end_date: str | None) -> None:
        if start_date is None and end_date is None:
            return
        start, end = QlibDataAdapter.validate_dates(start_date, end_date)
        if (start, end) != (cls.RESEARCH.start, cls.RESEARCH.end):
            raise ValueError(f"Qlib 研究时间范围固定为 {cls.RESEARCH.start} ~ {cls.RESEARCH.end}，不允许修改")

    @staticmethod
    def adapter_dates(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
        return QlibDataAdapter.validate_dates(start_date, end_date)

    def build_snapshot(self, stock_codes: Iterable[str] | None = None, run_id: str | None = None) -> TimeSplitSnapshot:
        codes = self.adapter.normalize_stock_codes(stock_codes)
        stages: dict[str, StageCoverage] = {}
        errors: list[str] = []
        for name, date_range in self.STAGES.items():
            try:
                report = self.adapter.get_coverage(codes, date_range.start, date_range.end)
                stages[name] = StageCoverage(
                    requested=date_range,
                    actual_start=report.min_trade_date,
                    actual_end=report.max_trade_date,
                    row_count=report.row_count,
                    stock_count=report.stock_count,
                    trade_date_count=report.trade_date_count,
                    status=report.status,
                    issues=report.issues,
                )
                if report.status == "blocked":
                    errors.append(f"{name}: 数据覆盖不足")
            except Exception as exc:  # noqa: BLE001
                stages[name] = StageCoverage(date_range, None, None, 0, 0, 0, "blocked", [{"message": str(exc), "blocked": True}])
                errors.append(f"{name}: {exc}")
        return TimeSplitSnapshot(
            split_version=SPLIT_VERSION,
            research=self.RESEARCH,
            stages=stages,
            stock_codes=codes,
            status="blocked" if errors else "healthy",
            errors=errors,
            data_snapshot_id=str(uuid.uuid4()),
            run_id=run_id,
        )

    def save_snapshot(self, snapshot: TimeSplitSnapshot) -> str:
        run_id = snapshot.run_id or str(uuid.uuid4())
        snapshot.run_id = run_id
        execute_update(
            "INSERT INTO qlib_research_run (run_id, split_version, status, snapshot_json) VALUES (%s, %s, %s, %s)",
            (run_id, snapshot.split_version, snapshot.status, json.dumps(snapshot.to_dict(), ensure_ascii=False)),
        )
        return run_id

    @staticmethod
    def get_snapshot(run_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT snapshot_json FROM qlib_research_run WHERE run_id=%s", (run_id,))
        if not rows:
            return None
        return json.loads(rows[0]["snapshot_json"])


service = FixedTimeSplitService()


def init_qlib_time_split_schema() -> None:
    execute_update(
        """
        CREATE TABLE IF NOT EXISTS qlib_research_run (
            run_id VARCHAR(64) NOT NULL PRIMARY KEY,
            split_version VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL,
            snapshot_json JSON NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_qlib_research_run_split (split_version, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
