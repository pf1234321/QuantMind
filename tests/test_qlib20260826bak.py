"""Export the configured stock universe from MySQL to Qlib and run research.

The script only reads ``trade_stock_daily`` rows for ``tests/stock.csv``.
Set ``QLIB_EXPORT_ONLY=1`` to stop after exporting and initializing Qlib.
"""

from pathlib import Path
import contextlib
import io
import logging
import os
import pickle
import warnings
from typing import Any, cast

# Qlib 0.9.7 默认使用本地 mlruns 文件存储；新版 MLflow 默认禁止该后端写入。
# 必须在导入 Qlib/MLflow 前设置兼容开关，否则 LightGBM 训练首轮记录指标时会失败。
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

# 研究脚本只保留关键业务输出，隐藏 Qlib/MLflow 的框架 INFO 日志。
for logger_name in (
    "qlib",
    "qlib.workflow",
    "qlib.data",
    "qlib.backtest",
    "qlib.BaseExecutor",
    "qlib.online",
    "qlib.Initialization",
):
    logging.getLogger(logger_name).setLevel(logging.ERROR)

warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="Could not infer format")
os.environ.setdefault("_QLIB_LOG_LEVEL", "ERROR")

import akshare as ak
import mlflow
import numpy as np
import pandas as pd
import pymysql
from scipy.stats import spearmanr
from sklearn.decomposition import PCA as SklearnPCA

# Qlib 导入链会输出可选模型和 Gym 的提示；这些依赖不是本脚本需要的功能。
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import qlib
    from qlib.backtest import backtest
    from qlib.constant import REG_CN
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.processor import Processor
    from qlib.data.storage.file_storage import (
        FileCalendarStorage,
        FileFeatureStorage,
        FileInstrumentStorage,
    )
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R
    from qlib.workflow.record_temp import PortAnaRecord, SignalRecord

# Qlib 0.9.7 的回测模块默认显示 tqdm 进度条，这里保留业务阶段输出即可。
class _SilentProgress:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_SilentProgress":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None


backtest_module = cast(Any, __import__("qlib.backtest.backtest", fromlist=["tqdm"]))
backtest_module.tqdm = _SilentProgress

# 实验记录不再执行 git diff/status，避免项目未初始化 Git 时打印大量命令帮助。
from qlib.workflow.recorder import MLflowRecorder
MLflowRecorder._log_uncommitted_code = lambda self: None


# 项目根目录和自定义股票池文件。脚本只分析 stock.csv 中列出的股票，不扫描全市场。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STOCK_FILE = PROJECT_ROOT / "tests" / "stock.csv"

# 数据库连接参数支持环境变量覆盖，便于在不同环境执行脚本。
DB_CONFIG = {
    # 默认跟随主应用 app/config.py 的 MySQL 配置；QLIB_DB_* 可单独覆盖研究脚本。
    "host": os.getenv("QLIB_DB_HOST", os.getenv("WUCAI_SQL_HOST", "localhost")),
    "port": int(os.getenv("QLIB_DB_PORT", os.getenv("WUCAI_SQL_PORT", "3309"))),
    "user": os.getenv("QLIB_DB_USER", os.getenv("WUCAI_SQL_USERNAME", "root")),
    "password": os.getenv("QLIB_DB_PASSWORD", os.getenv("WUCAI_SQL_PASSWORD", "root")),
    "database": os.getenv("QLIB_DB_NAME", os.getenv("WUCAI_SQL_DB", "wucai_trade")),
    "charset": "utf8mb4",
}
# 导出数据的总时间范围，以及 Qlib 二进制文件的保存目录。
START_DATE = os.getenv("QLIB_START_DATE", "2022-01-04")
END_DATE = os.getenv("QLIB_END_DATE", "2026-08-24")
QLIB_DIR = Path(os.getenv("QLIB_PROVIDER_DIR", "~/.qlib/mysql_cn_data")).expanduser()

# 严格按时间顺序划分数据，测试集不能参与训练和预处理拟合。
TRAIN_START, TRAIN_END = "2022-01-04", "2024-12-31"
VALID_START, VALID_END = "2025-01-01", "2025-12-31"
TEST_START, TEST_END = "2026-01-01", "2026-08-24"
PCA_COMPONENTS = int(os.getenv("QLIB_PCA_COMPONENTS", "10"))
TOPK = int(os.getenv("QLIB_TOPK", "20"))
HOLD_THRESH = int(os.getenv("QLIB_HOLD_THRESH", "10"))
N_DROP = int(os.getenv("QLIB_N_DROP", "3"))
BENCHMARK = "SH000300"


class FeaturePCA(Processor):
    """将 Alpha158 特征压缩为固定数量的 PCA 特征。"""

    def __init__(self, n_components=10, fit_start_time=None, fit_end_time=None):
        self.n_components = n_components
        self.fit_start_time = fit_start_time
        self.fit_end_time = fit_end_time
        self.pca = SklearnPCA(n_components=n_components)
        self.feature_columns = None
        self.fill_values = None

    def fit(self, df: Any = None):
        if df is None:
            raise ValueError("FeaturePCA.fit requires a DataFrame")
        if self.fit_start_time is None or self.fit_end_time is None:
            raise ValueError("FeaturePCA requires fit_start_time and fit_end_time")
        train_df = df.loc[
            (df.index.get_level_values("datetime") >= pd.Timestamp(self.fit_start_time))
            & (df.index.get_level_values("datetime") <= pd.Timestamp(self.fit_end_time))
        ]
        self.feature_columns = [column for column in df.columns if column[0] == "feature"]
        if not self.feature_columns:
            raise ValueError("Alpha158 did not produce feature columns")
        train_features = train_df[self.feature_columns].replace([np.inf, -np.inf], np.nan)
        self.fill_values = train_features.median().fillna(0.0)
        train_features = train_features.fillna(self.fill_values)
        self.pca.fit(train_features.to_numpy(dtype=float))

    def __call__(self, df: pd.DataFrame):
        if self.feature_columns is None:
            raise ValueError("FeaturePCA must be fitted before use")
        if self.fill_values is None:
            raise ValueError("FeaturePCA fill values are not fitted")
        features = df[self.feature_columns].replace([np.inf, -np.inf], np.nan)
        features = features.fillna(self.fill_values)
        transformed = self.pca.transform(features.to_numpy(dtype=float))
        pca_columns = pd.MultiIndex.from_tuples(
            [("feature", f"feature_pca_{index}") for index in range(self.n_components)],
            names=df.columns.names,
        )
        pca_frame = pd.DataFrame(transformed, index=df.index, columns=pca_columns)
        remaining = df.drop(columns=self.feature_columns)
        return pd.concat([pca_frame, remaining], axis=1)



def load_stock_codes() -> list[str]:
    """读取并规范化自定义股票池，仅保留 6 位数字股票代码。"""
    codes = pd.read_csv(STOCK_FILE, header=None, dtype=str)[0].str.strip()
    codes = codes[codes.str.fullmatch(r"\d{6}")].drop_duplicates().tolist()
    if not codes:
        raise ValueError(f"stock universe is empty: {STOCK_FILE}")
    return codes


def qlib_instrument(code: str) -> str:
    """将数字股票代码转换为 Qlib 中国市场的交易所代码格式。"""
    if code.startswith(("60", "68")):
        return f"SH{code}"
    if code.startswith(("00", "30")):
        return f"SZ{code}"
    if code.startswith(("4", "8")):
        return f"BJ{code}"
    raise ValueError(f"unsupported stock code: {code}")


def load_market_data(stock_codes: list[str]) -> pd.DataFrame:
    """从 trade_stock_daily 读取指定股票和日期范围的前复权日线。"""
    # 使用参数占位符，股票代码和日期不会直接拼接到 SQL 中。
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT
            trade_date AS datetime,
            stock_code AS stock_code,
            open_price AS open,
            high_price AS high,
            low_price AS low,
            close_price AS close,
            volume AS volume,
            amount AS money,
            1.0 AS factor
        FROM trade_stock_daily
        WHERE stock_code IN ({placeholders})
          AND trade_date BETWEEN %s AND %s
          AND adjustflag = 2
        ORDER BY trade_date, stock_code
    """
    # adjustflag=2 表示前复权，和 trade_stock_daily.close_price 的字段口径保持一致。
    connection = pymysql.connect(**DB_CONFIG)
    try:
        df = pd.read_sql(sql, cast(Any, connection), params=tuple([*stock_codes, START_DATE, END_DATE]))
    finally:
        connection.close()

    if df.empty:
        raise RuntimeError(
            f"trade_stock_daily has no adjustflag=2 data for {len(stock_codes)} stocks "
            f"between {START_DATE} and {END_DATE}"
        )

    # 将数据库日期、股票代码和数值字段转换为 Qlib 可接受的类型。
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["instrument"] = df["stock_code"].map(qlib_instrument)
    df = df.drop(columns=["stock_code"])
    numeric_columns = ["open", "high", "low", "close", "volume", "money", "factor"]
    df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors="coerce")
    # 丢弃关键字段为空的行，并按 Qlib 的 datetime/instrument 唯一键去重。
    df = df.dropna(subset=["datetime", "instrument", "open", "high", "low", "close", "volume", "money"])
    df = df.drop_duplicates(subset=["datetime", "instrument"], keep="last")
    return df.set_index(["datetime", "instrument"]).sort_index()


def load_benchmark_data() -> pd.DataFrame:
    """读取沪深300指数日线，并转换为 Qlib 的指数 instrument。"""
    benchmark = ak.stock_zh_index_daily(symbol="sh000300")
    if benchmark is None or benchmark.empty:
        raise RuntimeError("无法读取沪深300指数 SH000300 行情")
    benchmark = benchmark.rename(
        columns={
            "date": "datetime",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "money",
        }
    )
    required_columns = ["datetime", "open", "high", "low", "close"]
    missing_columns = [column for column in required_columns if column not in benchmark.columns]
    if missing_columns:
        raise RuntimeError(f"沪深300指数数据缺少字段：{missing_columns}")
    for column in ("volume", "money"):
        if column not in benchmark.columns:
            benchmark[column] = 0.0
    benchmark = benchmark[
        ["datetime", "open", "high", "low", "close", "volume", "money"]
    ].copy()
    benchmark["datetime"] = pd.to_datetime(benchmark["datetime"])
    benchmark["instrument"] = BENCHMARK
    benchmark["factor"] = 1.0
    numeric_columns = ["open", "high", "low", "close", "volume", "money", "factor"]
    benchmark[numeric_columns] = benchmark[numeric_columns].apply(pd.to_numeric, errors="coerce")
    benchmark = benchmark.dropna(subset=required_columns)
    return benchmark.set_index(["datetime", "instrument"]).sort_index()


def export_to_qlib(df: pd.DataFrame) -> list[str]:
    """按 pyqlib 0.9.7 的文件存储接口写入日频行情并返回可回测股票池。"""
    provider_uri = {"day": str(QLIB_DIR)}
    qlib.init(provider_uri=provider_uri, region=REG_CN)
    instrument_groups = list(df.groupby(level="instrument", sort=True))
    if not instrument_groups:
        raise ValueError("没有可导出的股票行情")

    benchmark_frame = df.xs(BENCHMARK, level="instrument", drop_level=False)
    calendar = pd.DatetimeIndex(
        benchmark_frame.index.get_level_values("datetime").unique().sort_values()
    )
    if calendar.empty:
        raise ValueError("基准没有可用的行情日期")

    # 回测期间不能允许停牌、上市不足或行情缺失的股票进入交易池，否则 Qlib
    # 会用 NaN 收盘价计算组合收益，导致收益和回撤失真。
    required_fields = ["open", "high", "low", "close", "volume", "money", "factor"]
    test_calendar = calendar[
        (calendar >= pd.Timestamp(TEST_START)) & (calendar <= pd.Timestamp(TEST_END))
    ]
    eligible_groups: list[tuple[str, pd.DataFrame]] = []
    excluded_instruments: list[str] = []
    for instrument, instrument_df in instrument_groups:
        if instrument == BENCHMARK:
            eligible_groups.append((instrument, instrument_df))
            continue
        test_values = instrument_df.droplevel("instrument").reindex(test_calendar)
        if test_values[required_fields].isna().any().any():
            excluded_instruments.append(str(instrument))
            continue
        eligible_groups.append((str(instrument), instrument_df))

    if excluded_instruments:
        print(f"测试期行情不完整，排除股票：{len(excluded_instruments)} 只")
    instrument_groups = eligible_groups
    eligible_instruments = sorted(
        instrument for instrument, _ in instrument_groups if instrument != BENCHMARK
    )
    if not eligible_instruments:
        raise ValueError("没有测试期行情完整的股票可供回测")

    calendar_storage = FileCalendarStorage("day", future=False, provider_uri=provider_uri)
    calendar_storage.uri.parent.mkdir(parents=True, exist_ok=True)
    calendar_values = [timestamp.strftime("%Y-%m-%d") for timestamp in calendar]
    calendar_storage._write_calendar(calendar_values)

    # 回测最后一个交易步会访问 end_time 之后的下一条日历边界。
    # 该日期只用于定义区间右边界，不写入任何股票行情，也不会参与交易。
    future_storage = FileCalendarStorage("day", future=True, provider_uri=provider_uri)
    future_storage.uri.parent.mkdir(parents=True, exist_ok=True)
    boundary_date = (calendar[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    future_storage._write_calendar(calendar_values + [boundary_date])

    instrument_data = {}
    for instrument, instrument_df in instrument_groups:
        instrument_name = str(instrument)
        instrument_data[instrument_name] = [
            (calendar[0], calendar[-1])
        ]
    instrument_storage = FileInstrumentStorage("all", "day", provider_uri=provider_uri)
    instrument_storage.uri.parent.mkdir(parents=True, exist_ok=True)
    # Qlib 0.9.7 的读取器要求 instrument\tstart_datetime\tend_datetime，
    # 其 _write_instrument 在该版本会再次覆盖文件并写成日期在前的顺序，
    # 因此这里直接按读取器要求写入，避免回测把股票代码当成日期解析。
    with instrument_storage.uri.open("w", encoding="utf-8") as instrument_file:
        for instrument_name, ranges in sorted(instrument_data.items()):
            for start_datetime, end_datetime in ranges:
                instrument_file.write(
                    f"{instrument_name}\t{start_datetime:%Y-%m-%d}"
                    f"\t{end_datetime:%Y-%m-%d}\n"
                )

    calendar_index = pd.Index(calendar)
    for instrument, instrument_df in instrument_groups:
        instrument_name = str(instrument)
        values = instrument_df.droplevel("instrument").reindex(calendar_index)
        for field in ["open", "high", "low", "close", "volume", "money", "factor"]:
            storage = FileFeatureStorage(instrument_name, field, "day", provider_uri=provider_uri)
            storage.uri.parent.mkdir(parents=True, exist_ok=True)
            if storage.uri.exists():
                storage.uri.unlink()
            storage.write(values[field].to_numpy(dtype="<f4", na_value=np.nan), index=0)

    return eligible_instruments


def _as_score_frame(prediction: pd.Series | pd.DataFrame) -> pd.DataFrame:
    """统一 Qlib 不同版本的预测返回值，得到标准 score DataFrame。"""
    # Qlib 可能返回 Series，也可能返回单列 DataFrame，这里统一为 score 列。
    if isinstance(prediction, pd.Series):
        result = prediction.rename("score").to_frame()
    else:
        result = prediction.copy()
        if "score" not in result.columns:
            if len(result.columns) != 1:
                raise ValueError(f"无法确定预测分数列: {list(result.columns)}")
            result = result.rename(columns={result.columns[0]: "score"})
    # 预测结果必须同时包含交易日期和股票代码，后续才能按时间切分和回测。
    if not isinstance(result.index, pd.MultiIndex) or result.index.nlevels != 2:
        raise ValueError("预测结果必须使用 MultiIndex(datetime, instrument)")
    result.index = result.index.set_names(["datetime", "instrument"])
    result["score"] = pd.to_numeric(result["score"], errors="coerce")
    return result.dropna(subset=["score"]).sort_index()


def _as_label_series(label_frame: Any) -> pd.Series:
    """统一 Qlib 标签返回值，兼容扁平列和 MultiIndex 列。"""
    if isinstance(label_frame, pd.Series):
        label = label_frame.rename("label")
    elif isinstance(label_frame.columns, pd.MultiIndex):
        # Qlib 标签列通常形如 ('label', 'LABEL0')，字段组位于第一层。
        label_columns = [column for column in label_frame.columns if column[0] == "label"]
        if len(label_columns) != 1:
            raise ValueError(f"无法确定标签列: {list(label_frame.columns)}")
        label = label_frame.loc[:, label_columns[0]].rename("label")
    elif "label" in label_frame.columns:
        label = label_frame["label"].rename("label")
    elif len(label_frame.columns) == 1:
        label = label_frame.iloc[:, 0].rename("label")
    else:
        raise ValueError(f"无法确定标签列: {list(label_frame.columns)}")
    label.index = label.index.set_names(["datetime", "instrument"])
    return pd.to_numeric(label, errors="coerce").sort_index()


def _aligned_factor_report(
    factor: pd.Series, label: pd.Series, min_cross_section: int = 10
) -> dict:
    """先按 datetime/instrument 对齐因子和标签，再计算 IC/ICIR。"""
    aligned = pd.concat([factor.rename("factor"), label.rename("label")], axis=1).dropna()
    aligned = aligned.groupby(level="datetime", group_keys=False).filter(
        lambda frame: len(frame) >= min_cross_section
    )
    if aligned.empty:
        raise ValueError("因子和标签没有可对齐的有效样本")

    daily_ic = aligned.groupby(level="datetime", sort=True).apply(
        lambda frame: spearmanr(frame["factor"], frame["label"], nan_policy="omit").statistic
    ).dropna()
    if daily_ic.empty:
        raise ValueError("没有足够的横截面样本计算 IC")
    ic_mean = float(daily_ic.mean())
    ic_std = float(daily_ic.std(ddof=1))
    return {
        "ic_mean": ic_mean,
        "icir": ic_mean / ic_std * (len(daily_ic) ** 0.5) if ic_std else float("nan"),
        "daily_ic": daily_ic,
    }


def _print_metric_report(name: str, factor: pd.Series, label: pd.Series) -> dict:
    report = _aligned_factor_report(factor, label)
    print(
        f"{name}: 样本数={factor.shape[0]:,} | "
        f"IC均值={report['ic_mean']:.4f} | ICIR={report['icir']:.4f}"
    )
    return report


def run_research(instruments: list[str]) -> None:
    """执行 Alpha158-PCA、LightGBM 训练、分段诊断和测试集回测。"""
    # PCA 和归一化处理器只在训练区间拟合，避免验证集和测试集数据泄漏。
    handler = Alpha158(
        start_time=START_DATE,
        end_time=END_DATE,
        fit_start_time=TRAIN_START,
        fit_end_time=TRAIN_END,
        # 选股股票池
        instruments=instruments,
        # Qlib 0.9.7 使用 infer_processors/learn_processors；特征处理必须放在 infer 阶段。
        infer_processors=[
            # RobustZScoreNorm 只用训练区间拟合，避免验证集和测试集信息泄漏。
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            # 横截面标准化按交易日处理 Alpha158 特征。
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
            # Qlib 0.9.7 没有内置 PCA，使用实现了 Qlib Processor 接口的本地处理器。
            FeaturePCA(
                n_components=PCA_COMPONENTS,
                fit_start_time=TRAIN_START,
                fit_end_time=TRAIN_END,
            ),
        ],
        # 学习阶段删除没有未来收益标签的样本，并对标签做横截面标准化。
        learn_processors=[
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
    )
    # DatasetH 只负责时间切分，训练、验证、测试区间严格按时间先后排列。
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": (TRAIN_START, TRAIN_END),
            "valid": (VALID_START, VALID_END),
            "test": (TEST_START, TEST_END),
        },
    )
    print(f"PCA 分量数：{PCA_COMPONENTS}")
    # 保留足够的树容量，让模型学习横截面排序；正则化交给验证集早停控制。
    model = LGBModel(
        loss="mse",
        learning_rate=0.03,
        num_leaves=31,
        max_depth=-1,
        min_data_in_leaf=30,
        feature_fraction=0.9,
        lambda_l1=0.0,
        lambda_l2=10.0,
        num_boost_round=1000,
        early_stopping_rounds=50,
        seed=42,
        bagging_seed=42,
        feature_fraction_seed=42,
    )
    print("开始训练 LightGBM 模型...")
    model.fit(dataset)

    # 分段预测，避免 Qlib 默认只返回某一个 segment，导致指标范围混淆。
    predictions_by_segment = {
        segment_name: _as_score_frame(model.predict(dataset, segment=segment_name))
        for segment_name in ("train", "valid", "test")
    }
    pred_df = pd.concat(predictions_by_segment.values()).sort_index()
    print("模型训练完成，前 5 行预测打分：")
    print(pred_df.head())
    print("预测分数统计：")
    print(pred_df["score"].describe())
    print(
        f"预测分数唯一值：{pred_df['score'].nunique():,} / {len(pred_df):,}，"
        f"重复率={1 - pred_df['score'].nunique() / max(len(pred_df), 1):.2%}"
    )
    test_signal = predictions_by_segment["test"]
    daily_unique_scores = test_signal["score"].groupby(level="datetime").nunique()
    daily_instruments = test_signal["score"].groupby(level="datetime").size()
    print(
        f"测试信号范围：{test_signal.index.get_level_values('datetime').min()} ~ "
        f"{test_signal.index.get_level_values('datetime').max()}，"
        f"每日股票数={daily_instruments.min()}~{daily_instruments.max()}，"
        f"每日分数唯一值={daily_unique_scores.min()}~{daily_unique_scores.max()}"
    )
    booster = getattr(model, "model", None)
    best_iteration = getattr(booster, "best_iteration", None)
    if best_iteration is not None:
        print(f"模型实际最佳迭代轮数：{best_iteration}")

    # 保存模型，文件名标明 Alpha158、LightGBM 和当前 42 只股票池。
    model_path = PROJECT_ROOT / "data" / "models" / "lgb_alpha158_custom_42_model.pkl"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as model_file:
        pickle.dump(model, model_file)
    print(f"模型已保存：{model_path}")

    # 读取 PCA 因子原材料，后续只在测试集上做逐因子诊断。
    # Qlib 0.9.7 的 fetch(col_set=列表) 会把列表解释为顶层字段组，
    # 因此先读取 feature 组并去掉字段组层级，再选择 PCA 列。
    pca_columns = [f"feature_pca_{index}" for index in range(PCA_COMPONENTS)]
    feature_df = handler.fetch(col_set="feature")
    missing_pca_columns = [column for column in pca_columns if column not in feature_df.columns]
    if missing_pca_columns:
        raise KeyError(f"PCA 特征未生成: {missing_pca_columns}")
    pca_df = feature_df.loc[:, pca_columns]

    segments = {
        "train": (TRAIN_START, TRAIN_END),
        "valid": (VALID_START, VALID_END),
        "test": (TEST_START, TEST_END),
    }
    # 标签也按 segment 单独读取，避免默认读取范围与预测结果不一致。
    labels_by_segment: dict[str, pd.Series] = {}
    for segment_name in segments:
        label_frame = dataset.prepare(segments=segment_name, col_set=["label"], data_key="learn")
        labels_by_segment[segment_name] = _as_label_series(label_frame)

    print("\\nPCA 因子和 LightGBM 模型分段诊断：")
    print("说明：train 模型 score 是样本内预测，泛化能力以 valid/test 为准。")
    reports: dict[str, dict] = {}
    for segment_name, (start_date, end_date) in segments.items():
        segment_predictions = predictions_by_segment[segment_name]["score"]
        segment_labels = labels_by_segment[segment_name]
        reports[segment_name] = {
            "model": _print_metric_report(
                f"{segment_name} 模型 score"
                + (" (in-sample)" if segment_name == "train" else ""),
                segment_predictions,
                segment_labels,
            ),
        }
        if segment_name == "test":
            pca_mask = (
                (pca_df.index.get_level_values("datetime") >= pd.Timestamp(start_date))
                & (pca_df.index.get_level_values("datetime") <= pd.Timestamp(end_date))
            )
            for column in pca_columns:
                reports[segment_name][column] = _print_metric_report(
                    f"{segment_name} {column}", pca_df.loc[pca_mask, column], segment_labels
                )

    # 回测只使用测试集预测信号，训练集和验证集不会进入模拟交易。
    # 使用实际成功导出并产生测试信号的股票池，避免请求股票与有效数据不一致。
    test_signal = predictions_by_segment["test"]
    signal_instruments = sorted(
        {str(instrument) for instrument in test_signal.index.get_level_values("instrument")}
    )
    if not signal_instruments:
        raise ValueError("测试集没有有效预测信号，停止回测")
    missing_instruments = sorted(set(instruments) - set(signal_instruments))
    if missing_instruments:
        print(f"测试集无预测的股票：{missing_instruments}")
    # 默认持有10只，可通过 QLIB_TOPK 调整。
    topk = min(TOPK, len(signal_instruments))
    n_drop = min(N_DROP, max(1, topk - 1))
    hold_thresh = max(1, HOLD_THRESH)
    # TopkDropoutStrategy 按预测分数选股，定期淘汰部分持仓并补入高分股票。
    strategy_config = {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"signal": test_signal, "topk": topk, "n_drop": n_drop, "hold_thresh": hold_thresh},
    }
    # 使用日频模拟执行器，在测试区间内执行组合回测。
    executor_config = {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
    }
    benchmark = BENCHMARK
    print(
        f"开始执行测试集选股回测：TopK={topk}, n_drop={n_drop}, "
        f"hold_thresh={hold_thresh}, benchmark={benchmark}..."
    )
    backtest_res = backtest(
        strategy=init_instance_by_config(strategy_config),
        executor=init_instance_by_config(executor_config),
        start_time=TEST_START,
        end_time=TEST_END,
        benchmark=benchmark,
        account=1_000_000,
    )
    # print("回测结果：", backtest_res)

    # backtest_res 包含每天的完整持仓明细，避免直接打印造成大量无关输出。
    # backtest 返回 (portfolio_dict, indicator_dict)，组合净值在第一个返回值中。
    portfolio_metrics = backtest_res[0].get("1day", (None, None))[0]
    if portfolio_metrics is not None and not portfolio_metrics.empty:
        account_column = "account" if "account" in portfolio_metrics.columns else "value"
        account_values = portfolio_metrics[account_column].replace(0, np.nan).dropna()
        if not account_values.empty:
            start_value = float(account_values.iloc[0])
            end_value = float(account_values.iloc[-1])
            total_return = end_value / start_value - 1
            print(
                f"回测完成：起始净值={start_value:,.2f}，结束净值={end_value:,.2f}，"
                f"区间收益={total_return:.2%}"
            )
        else:
            print("回测完成，但账户净值列没有有效数据。")
    else:
        print("回测完成，但未生成有效组合净值。")

    # LGBModel.fit 会通过 Qlib 记录训练指标，但不会结束其 MLflow run。
    # 先关闭该活动 run，再单独记录信号和回测结果，避免重复 start_run。
    if mlflow.active_run() is not None:
        mlflow.end_run()

    # 将预测信号和回测结果写入 Qlib 实验记录，便于后续复盘和对比。
    with R.start(experiment_name="Alpha158_lightgbm_custom_42"):
        recorder = R.get_recorder()
        signal_record = SignalRecord(model, dataset, recorder=recorder)
        signal_record.generate()
        PortAnaRecord(
            recorder,
            {
                "strategy": strategy_config,
                "executor": executor_config,
                "backtest": {
                    "start_time": TEST_START,
                    "end_time": TEST_END,
                    "account": 1_000_000,
                    "benchmark": benchmark,
                },
            },
            risk_analysis_freq="day",
        ).generate()


def main() -> None:
    """主流程：读取股票池、导出行情、初始化 Qlib 并按需运行研究。"""
    stock_codes = load_stock_codes()
    print(f"股票池：{len(stock_codes)} 只，范围：{START_DATE} ~ {END_DATE}")
    df = load_market_data(stock_codes)
    print(f"读取行情：{len(df):,} 条，股票：{df.index.get_level_values('instrument').nunique()} 只")
    benchmark_df = load_benchmark_data()
    df = pd.concat([df, benchmark_df]).sort_index()
    print(f"已加载沪深300基准：{BENCHMARK}")
    eligible_instruments = export_to_qlib(df)
    print(f"Qlib 数据已导出并初始化：{QLIB_DIR}")
    print(f"测试期有效股票池：{len(eligible_instruments)} 只")
    # 仅导出模式用于先验证数据库查询和 Qlib 数据转换，不启动训练回测。
    if os.getenv("QLIB_EXPORT_ONLY", "0") != "1":
        run_research(eligible_instruments)


if __name__ == "__main__":
    main()
