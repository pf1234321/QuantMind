"""直接读取本地 Qlib Provider 的标准日线数据。"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.database import execute_query

QLIB_DATA_DIR = Path(os.getenv("QLIB_DATA_DIR", "~/.qlib/qlib_data/cn_data")).expanduser()
QLIB_COLUMNS = ["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"]

REQUIRED_ADJUSTFLAG = 2
QLIB_COLUMNS = ["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"]


@dataclass
class DataIssue:
    issue_type: str
    message: str
    count: int = 0
    stock_codes: list[str] = field(default_factory=list)
    sample_dates: list[str] = field(default_factory=list)
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageReport:
    source: str
    adapter: str
    status: str
    min_trade_date: str | None
    max_trade_date: str | None
    stock_count: int
    trade_date_count: int
    row_count: int
    adjustflag: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    requested_start_date: str | None = None
    requested_end_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QlibDataAdapter:
    """从本地 Qlib Provider 查询并规范化行情；该类不会执行写操作。"""

    def __init__(self, required_adjustflag: int = REQUIRED_ADJUSTFLAG, batch_size: int = 500):
        self.required_adjustflag = required_adjustflag
        self.batch_size = max(1, batch_size)
        self._initialized = False

    @staticmethod
    def normalize_code(stock_code: Any) -> str:
        code = QlibDataAdapter.database_code(stock_code)
        if not code:
            return ""
        if code.startswith(("6",)):
            market = "SH"
        elif code.startswith(("8", "4")):
            market = "BJ"
        else:
            market = "SZ"
        return f"{market}{code.zfill(6)}"

    @staticmethod
    def database_code(stock_code: str) -> str:
        code = str(stock_code or "").strip().upper().split(".", 1)[0]
        if len(code) > 6 and code[:2] in {"SH", "SZ", "BJ"}:
            code = code[2:]
        return code

    @staticmethod
    def validate_dates(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
        def parse(value: str | None) -> str | None:
            if value is None or value == "":
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
            except ValueError as exc:
                raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc

        start = parse(start_date)
        end = parse(end_date)
        if start and end and start > end:
            raise ValueError("开始日期不能晚于结束日期")
        return start, end

    @staticmethod
    def normalize_stock_codes(stock_codes: Iterable[str] | None) -> list[str]:
        if stock_codes is None:
            return []
        result = []
        for code in stock_codes:
            normalized = QlibDataAdapter.database_code(code)
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _where(self, stock_codes: list[str], start_date: str | None, end_date: str | None) -> tuple[str, list[Any]]:
        conditions = ["adjustflag=%s"]
        params: list[Any] = [self.required_adjustflag]
        if stock_codes:
            placeholders = ",".join(["%s"] * len(stock_codes))
            conditions.append(f"stock_code IN ({placeholders})")
            params.extend(stock_codes)
        if start_date:
            conditions.append("trade_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= %s")
            params.append(end_date)
        return " AND ".join(conditions), params

    def _init_qlib(self) -> Any:
        if not self._initialized:
            import qlib
            from qlib.constant import REG_CN

            qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
            self._initialized = True
        from qlib.data import D
        return D

    def get_data(
        self,
        stock_codes: Iterable[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        start_date, end_date = self.validate_dates(start_date, end_date)
        codes = self.normalize_stock_codes(stock_codes)
        instruments = [self.normalize_code(code) for code in codes] if codes else "csi300"
        fields = ["$open", "$high", "$low", "$close", "$volume", "$amount"]
        frame = self._init_qlib().features(
            instruments=instruments,
            fields=fields,
            start_time=start_date,
            end_time=end_date,
        )
        if frame.empty:
            return pd.DataFrame(columns=QLIB_COLUMNS + ["source_stock_code", "adjustflag"])
        frame = frame.rename(columns={
            "$open": "open", "$high": "high", "$low": "low",
            "$close": "close", "$volume": "volume", "$amount": "amount",
        }).reset_index()
        frame = frame.rename(columns={"instrument": "instrument", "datetime": "datetime"})
        frame["source_stock_code"] = frame["instrument"].astype(str).str.upper()
        frame["adjustflag"] = self.required_adjustflag
        for column in ["open", "high", "low", "close", "volume", "amount"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        return frame[QLIB_COLUMNS + ["source_stock_code", "adjustflag"]].sort_values(
            ["datetime", "instrument"]
        ).reset_index(drop=True)

    def _query_rows(self, stock_codes: list[str], start_date: str | None, end_date: str | None) -> list[dict[str, Any]]:
        where, params = self._where(stock_codes, start_date, end_date)
        return execute_query(
            "SELECT stock_code, trade_date, open_price, high_price, low_price, close_price, "
            "volume, amount, adjustflag FROM trade_stock_daily "
            f"WHERE {where} ORDER BY trade_date, stock_code",
            params,
        )

    def get_qlib_records(
        self,
        stock_codes: Iterable[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        frame = self.get_data(stock_codes, start_date, end_date)
        records = [dict(record) for record in frame.to_dict(orient="records")]
        for record in records:
            record["datetime"] = record["datetime"].strftime("%Y-%m-%d")
        return records

    def get_coverage(
        self,
        stock_codes: Iterable[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CoverageReport:
        start_date, end_date = self.validate_dates(start_date, end_date)
        codes = self.normalize_stock_codes(stock_codes)
        frame = self.get_data(codes, start_date, end_date)
        row = {
            "min_trade_date": frame["datetime"].min() if not frame.empty else None,
            "max_trade_date": frame["datetime"].max() if not frame.empty else None,
            "stock_count": frame["instrument"].nunique() if not frame.empty else 0,
            "trade_date_count": frame["datetime"].nunique() if not frame.empty else 0,
            "row_count": len(frame),
        }
        min_date = self._date_string(row.get("min_trade_date"))
        max_date = self._date_string(row.get("max_trade_date"))
        issues = self._coverage_issues(codes, start_date, end_date, row, frame)
        status = self._status(issues)
        return CoverageReport(
            source=str(QLIB_DATA_DIR),
            adapter="qlib",
            status=status,
            min_trade_date=min_date,
            max_trade_date=max_date,
            stock_count=int(row.get("stock_count") or 0),
            trade_date_count=int(row.get("trade_date_count") or 0),
            row_count=int(row.get("row_count") or 0),
            adjustflag=self.required_adjustflag,
            issues=[issue.to_dict() for issue in issues],
            stock_codes=codes,
            requested_start_date=start_date,
            requested_end_date=end_date,
        )

    def get_status(self) -> dict[str, Any]:
        """返回数据源状态；失败时返回不可用状态而不是伪造统计值。"""
        checked_at = datetime.now().isoformat(timespec="seconds")
        try:
            report = self.get_coverage()
            issues = list(report.issues)
            try:
                sync_rows = execute_query(
                    "SELECT finished_at FROM sync_task_log "
                    "WHERE task_name=%s AND status=%s AND finished_at IS NOT NULL "
                    "ORDER BY finished_at DESC LIMIT 1",
                    ("kline", "success"),
                )
                last_sync_at = self._datetime_string(sync_rows[0].get("finished_at")) if sync_rows else None
            except Exception:
                last_sync_at = None
            if last_sync_at is None:
                issues.append(DataIssue("sync_time_unknown", "无法确认最近一次行情同步完成时间").to_dict())
            quality_status = report.status
            status = "healthy" if quality_status == "healthy" else "warning" if quality_status == "warning" else "abnormal"
            if any(issue.get("blocked") for issue in issues):
                status = "abnormal"
            return {
                "source": str(QLIB_DATA_DIR),
                "pipeline": "Qlib Provider → Alpha158",
                "connection_status": "connected",
                "status": status,
                "quality_status": quality_status,
                "min_trade_date": report.min_trade_date,
                "max_trade_date": report.max_trade_date,
                "stock_count": report.stock_count,
                "trade_date_count": report.trade_date_count,
                "row_count": report.row_count,
                "last_sync_at": last_sync_at,
                "last_sync_source": "sync_log" if last_sync_at else "unknown",
                "checked_at": checked_at,
                "issues": issues,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "source": str(QLIB_DATA_DIR),
                "pipeline": "Qlib Provider → Alpha158",
                "connection_status": "disconnected",
                "status": "unavailable",
                "quality_status": "blocked",
                "min_trade_date": None,
                "max_trade_date": None,
                "stock_count": 0,
                "trade_date_count": 0,
                "row_count": 0,
                "last_sync_at": None,
                "last_sync_source": "unknown",
                "checked_at": checked_at,
                "issues": [{"issue_type": "data_source_unavailable", "message": str(exc), "blocked": True}],
            }

    def validate_data(
        self,
        stock_codes: Iterable[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CoverageReport:
        """校验 Qlib 数据可用性；边界 NaN 交由 Alpha158 处理，不阻断任务。"""
        start_date, end_date = self.validate_dates(start_date, end_date)
        codes = self.normalize_stock_codes(stock_codes)
        return self.get_coverage(codes, start_date, end_date)

    def _coverage_issues(
        self,
        codes: list[str],
        start_date: str | None,
        end_date: str | None,
        summary: dict[str, Any],
        frame: pd.DataFrame,
    ) -> list[DataIssue]:
        issues: list[DataIssue] = []
        if not summary or not summary.get("row_count"):
            issues.append(DataIssue("no_data", "指定范围没有前复权行情数据", blocked=True))
            return issues
        # 起始日允许是周末或交易所节假日，区间内存在首个交易日即可。
        # 结束日仍需覆盖到请求日；否则可能缺少最新行情。
        actual_max_date = self._date_string(summary.get("max_trade_date"))
        if end_date and actual_max_date and actual_max_date < end_date:
            issues.append(DataIssue("end_date_coverage", "实际最新行情早于请求结束日期", blocked=True))
        if codes:
            requested = set(codes)
            actual = {
                self.database_code(instrument)
                for instrument in frame["instrument"].dropna().unique()
            }
            missing = sorted(requested - actual)
            if missing:
                issues.append(DataIssue("unknown_stock", "股票池中没有对应的前复权行情", len(missing), missing, blocked=True))
        return issues

    def _frame_issues(self, frame: pd.DataFrame) -> list[DataIssue]:
        if frame.empty:
            return []
        issues: list[DataIssue] = []
        required = ["open", "high", "low", "close", "volume", "amount"]
        null_count = int(frame[required].isna().any(axis=1).sum())
        if null_count:
            issues.append(DataIssue("null_field", "行情必要字段存在空值", null_count, blocked=True))
        positive = frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
        if int((~positive).sum()):
            issues.append(DataIssue("invalid_price", "OHLC 存在小于等于 0 的价格", int((~positive).sum()), blocked=True))
        ohlc_valid = (
            frame["low"].le(frame[["open", "high", "close"]].min(axis=1))
            & frame["high"].ge(frame[["open", "high", "close"]].max(axis=1))
        )
        if int((~ohlc_valid).sum()):
            issues.append(DataIssue("invalid_ohlc", "OHLC 价格关系异常", int((~ohlc_valid).sum()), blocked=True))
        non_negative = frame[["volume", "amount"]].ge(0).all(axis=1)
        if int((~non_negative).sum()):
            issues.append(DataIssue("negative_turnover", "成交量或成交额为负数", int((~non_negative).sum()), blocked=True))
        duplicates = int(frame.duplicated(["instrument", "datetime"]).sum())
        if duplicates:
            issues.append(DataIssue("duplicate_record", "同一股票同一交易日存在重复行情", duplicates, blocked=True))
        return issues

    @staticmethod
    def _status(issues: list[DataIssue]) -> str:
        if any(issue.blocked for issue in issues):
            return "blocked"
        if issues:
            return "warning"
        return "healthy"

    @staticmethod
    def _date_string(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10]

    @staticmethod
    def _datetime_string(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        return str(value)


adapter = QlibDataAdapter()
