"""Use the local Qlib data provider to run research."""

from pathlib import Path
import contextlib
import io
import logging
import os
import pickle
import time
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

import mlflow
import numpy as np
import pandas as pd
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


# 项目根目录、研究数据时间范围，以及标准 Qlib 中国市场数据目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 研究数据时间范围：标准 Qlib 数据包覆盖 2018 年至本地 Qlib 最后完整交易日。
START_DATE = "2018-01-04"
QLIB_DIR = Path(os.getenv("QLIB_DATA_DIR", "~/.qlib/qlib_data/cn_data")).expanduser()


def _detect_qlib_last_date(data_dir: Path) -> str:
    """从本地 Qlib 交易日历读取最后日期，不使用服务器当前日期。"""
    calendar_path = data_dir / "calendars" / "day.txt"
    if not calendar_path.is_file():
        raise FileNotFoundError(f"本地 Qlib 交易日历不存在：{calendar_path}")
    dates = []
    for line in calendar_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = line.strip()[:10]
        try:
            dates.append(pd.Timestamp(value))
        except (TypeError, ValueError):
            continue
    if not dates:
        raise ValueError(f"本地 Qlib 交易日历没有有效日期：{calendar_path}")
    return max(dates).date().isoformat()


END_DATE = os.getenv("QLIB_END_DATE") or _detect_qlib_last_date(QLIB_DIR)

# 严格按时间顺序划分数据。
TRAIN_START: str = START_DATE
TRAIN_END = "2023-06-08"
VALID_START = "2023-06-09"
VALID_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END: str = END_DATE
PCA_COMPONENTS = int(os.getenv("QLIB_PCA_COMPONENTS", "10"))
TOPK = int(os.getenv("QLIB_TOPK", "10"))
HOLD_THRESH = int(os.getenv("QLIB_HOLD_THRESH", "10"))
N_DROP = int(os.getenv("QLIB_N_DROP", "2"))
BENCHMARK = "SH000300"
EVAL_SEGMENT = os.getenv("QLIB_EVAL_SEGMENT", "test")
SEGMENT_RANGES = {
    "train": (TRAIN_START, TRAIN_END),
    "valid": (VALID_START, VALID_END),
    "test": (TEST_START, TEST_END),
}


def _progress(message: str) -> None:
    """输出带时间的阶段进度，并立即刷新终端。"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


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
        _progress(
            f"PCA 开始拟合：训练样本={len(train_features):,}，特征数={len(self.feature_columns)}"
        )
        self.pca.fit(train_features.to_numpy(dtype=float))
        _progress("PCA 拟合完成")

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


def run_research(instruments: str | list[str]) -> None:
    """执行 Alpha158-PCA、LightGBM 训练、分段诊断和回测。"""
    _progress("开始创建 Alpha158 数据处理器；首次读取沪深300数据可能需要几分钟")
    # PCA 和归一化处理器只在训练区间拟合，避免验证集和测试集数据泄漏。
    handler = Alpha158(
        start_time=START_DATE,
        end_time=cast(str, END_DATE),
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
    _progress("Alpha158 数据处理器创建完成，开始建立 DatasetH 数据集")
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": (TRAIN_START, TRAIN_END),
            "valid": (VALID_START, VALID_END),
            "test": (TEST_START, TEST_END),
        },
    )
    _progress("DatasetH 创建完成，开始初始化 LightGBM 模型")
    print(f"PCA 分量数：{PCA_COMPONENTS}", flush=True)
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
        colsample_bytree=0.8879,
        subsample=0.8789,
        num_threads=20,
        seed=42,
        bagging_seed=42,
        feature_fraction_seed=42,
    )
    _progress("开始训练 LightGBM 模型；LightGBM 期间会持续消耗 CPU")
    model.fit(dataset)
    _progress("LightGBM 训练完成，开始分段预测")

    # 分段预测，避免 Qlib 默认只返回某一个 segment，导致指标范围混淆。
    predictions_by_segment = {}
    for segment_name in ("train", "valid", "test"):
        _progress(f"正在生成 {segment_name} 集预测")
        predictions_by_segment[segment_name] = _as_score_frame(
            model.predict(dataset, segment=segment_name)
        )
        _progress(f"{segment_name} 集预测完成：{len(predictions_by_segment[segment_name]):,} 条")
    pred_df = pd.concat(predictions_by_segment.values()).sort_index()
    print("模型训练完成，前 5 行预测打分：")
    print(pred_df.head())
    print("预测分数统计：")
    print(pred_df["score"].describe())
    score_unique = pred_df["score"].nunique()
    score_std = float(pred_df["score"].std())
    print(
        f"预测分数唯一值：{score_unique:,} / {len(pred_df):,}，"
        f"重复率={1 - score_unique / max(len(pred_df), 1):.2%}，"
        f"标准差={score_std:.6g}"
    )
    if score_unique <= 1 or not np.isfinite(score_std) or score_std <= 1e-12:
        raise ValueError("模型预测分数几乎恒定，停止回测；请检查特征处理和 LightGBM 参数")
    eval_signal = predictions_by_segment[EVAL_SEGMENT]
    daily_unique_scores = eval_signal["score"].groupby(level="datetime").nunique()
    daily_instruments = eval_signal["score"].groupby(level="datetime").size()
    print(
        f"{EVAL_SEGMENT} 信号范围：{eval_signal.index.get_level_values('datetime').min()} ~ "
        f"{eval_signal.index.get_level_values('datetime').max()}，"
        f"每日股票数={daily_instruments.min()}~{daily_instruments.max()}，"
        f"每日分数唯一值={daily_unique_scores.min()}~{daily_unique_scores.max()}"
    )
    booster = getattr(model, "model", None)
    best_iteration = getattr(booster, "best_iteration", None)
    if best_iteration is not None:
        print(f"模型实际最佳迭代轮数：{best_iteration}")

    # 保存模型，文件名包含特征类型、PCA 维度和训练/测试数据范围，便于区分实验版本。
    model_filename = (
        f"lgb_alpha158_pca{PCA_COMPONENTS}_cn_"
        f"train{TRAIN_START.replace('-', '')}_test{TEST_START.replace('-', '')}-"
        f"{TEST_END.replace('-', '')}.pkl"
    )
    model_path = PROJECT_ROOT / "data" / "models" / model_filename
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as model_file:
        pickle.dump(model, model_file)
    print(f"模型已保存：{model_path}")

    # 读取 PCA 特征原材料，后续只在测试集上做逐因子诊断。
    # Qlib 0.9.7 的 fetch(col_set=列表) 会把列表解释为顶层字段组，
    # 因此先读取 feature 组并去掉字段组层级，再选择 PCA 列。
    pca_columns = [f"feature_pca_{index}" for index in range(PCA_COMPONENTS)]
    _progress("开始读取 PCA 特征，用于测试集因子诊断")
    feature_df = handler.fetch(col_set="feature")
    _progress(f"PCA 特征读取完成：{len(feature_df):,} 条")
    missing_pca_columns = [column for column in pca_columns if column not in feature_df.columns]
    if missing_pca_columns:
        raise KeyError(f"PCA 特征未生成: {missing_pca_columns}")
    pca_df = feature_df.loc[:, pca_columns]

    segments = {
        "train": (TRAIN_START, TRAIN_END),
        "valid": (VALID_START, VALID_END),
        "test": (TEST_START, TEST_END),
    }
    labels_by_segment: dict[str, pd.Series] = {}
    for segment_name in segments:
        label_frame = dataset.prepare(segments=segment_name, col_set=["label"], data_key="learn")
        labels_by_segment[segment_name] = _as_label_series(label_frame)

    print("\nPCA 因子和 LightGBM 模型分段诊断：")
    print("说明：train 模型 score 是样本内预测，参数选择只看 valid，最终结果看 test。")
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
                (pca_df.index.get_level_values("datetime") >= pd.Timestamp(cast(str, start_date)))
                & (pca_df.index.get_level_values("datetime") <= pd.Timestamp(cast(str, end_date)))
            )
            for column in pca_columns:
                reports[segment_name][column] = _print_metric_report(
                    f"{segment_name} {column}", pca_df.loc[pca_mask, column], segment_labels
                )

    # 参数选择阶段可使用验证集；最终报告默认只使用测试集。
    eval_start, eval_end = SEGMENT_RANGES[EVAL_SEGMENT]
    signal_instruments = sorted(
        {str(instrument) for instrument in eval_signal.index.get_level_values("instrument")}
    )
    if not signal_instruments:
        raise ValueError("测试集没有有效预测信号，停止回测")
    if isinstance(instruments, list):
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
        "kwargs": {"signal": eval_signal, "topk": topk, "n_drop": n_drop, "hold_thresh": hold_thresh},
    }
    # 使用日频模拟执行器，在测试区间内执行组合回测。
    executor_config = {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {"time_per_step": "week", "generate_portfolio_metrics": True},
    }
    benchmark = BENCHMARK
    print(
        f"开始执行 {EVAL_SEGMENT} 集选股回测：TopK={topk}, n_drop={n_drop}, "
        f"hold_thresh={hold_thresh}, benchmark={benchmark}..."
    )
    _progress("开始执行测试集回测")
    backtest_res = backtest(
        strategy=init_instance_by_config(strategy_config),
        executor=init_instance_by_config(executor_config),
        start_time=eval_start,
        end_time=eval_end,
        benchmark=benchmark,
        account=1_000_000,
    )
    _progress(f"{EVAL_SEGMENT} 集回测计算完成，开始整理结果")
    # print("回测结果：", backtest_res)

    # backtest 返回 (portfolio_dict, indicator_dict)，组合净值在第一个返回值中。
    # time_per_step 改为 week 后，字典键不再固定是 1day，因此不能写死键名。
    portfolio_dict = backtest_res[0]
    portfolio_key = next(
        (key for key, value in portfolio_dict.items() if value and value[0] is not None),
        None,
    )

    portfolio_metrics = portfolio_dict[portfolio_key][0] if portfolio_key else None
    positions_by_date = portfolio_dict[portfolio_key][1] if portfolio_key else {}
    if portfolio_metrics is not None:
        print(portfolio_metrics)
        for dt, position in positions_by_date.items():
            amounts = {}
            stock_value = None
            total_value = None
            cash = None
            if hasattr(position, "get_stock_list"):
                hold_stocks = position.get_stock_list()
                stock_weights = position.get_stock_weight_dict(only_stock=True)
                all_weights = position.get_stock_weight_dict(only_stock=False)
                if hasattr(position, "get_stock_amount_dict"):
                    amounts = position.get_stock_amount_dict()
                if hasattr(position, "calculate_stock_value"):
                    stock_value = position.calculate_stock_value()
                if hasattr(position, "calculate_value"):
                    total_value = position.calculate_value()
                if hasattr(position, "get_cash"):
                    cash = position.get_cash()
            elif isinstance(position, dict):
                hold_stocks = list(position.keys())
                stock_weights = position
                all_weights = position
            else:
                hold_stocks = []
                stock_weights = {}
                all_weights = {}

            stock_weight_sum = sum(float(value) for value in stock_weights.values())
            all_weight_sum = sum(float(value) for value in all_weights.values())
            print(f"\n【{pd.Timestamp(dt).date()}】本期持仓 {len(hold_stocks)} 只：")
            print(
                f"  股票权重合计={stock_weight_sum:.2%}，"
                f"全部权重合计={all_weight_sum:.2%}"
            )
            if stock_value is not None or total_value is not None or cash is not None:
                stock_value_text = "未知" if stock_value is None else f"{float(stock_value):,.2f}"
                total_value_text = "未知" if total_value is None else f"{float(total_value):,.2f}"
                cash_text = "未知" if cash is None else f"{float(cash):,.2f}"
                print(
                    f"  股票市值={stock_value_text}，"
                    f"总资产={total_value_text}，现金={cash_text}"
                )
            for instrument in hold_stocks:
                weight = stock_weights.get(instrument)
                amount = amounts.get(instrument)
                details = []
                if amount is not None:
                    details.append(f"数量={float(amount):,.0f}")
                if weight is not None:
                    details.append(f"股票权重={float(weight):.2%}")
                print(f"  {instrument}: {', '.join(details) if details else '无估值信息'}")


    _progress(f"回测组合指标键：{portfolio_key or '无有效指标'}")
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
    with R.start(experiment_name="Alpha158_lightgbm_all"):
        recorder = R.get_recorder()
        signal_record = SignalRecord(model, dataset, recorder=recorder)
        signal_record.generate()
        PortAnaRecord(
            recorder,
            {
                "strategy": strategy_config,
                "executor": executor_config,
                "backtest": {
                    "start_time": cast(str, eval_start),
                    "end_time": cast(str, eval_end),
                    "account": 1_000_000,
                    "benchmark": benchmark,
                },
            },
            risk_analysis_freq="day",
        ).generate()


def main() -> None:
    """初始化标准 Qlib Provider，并使用全量股票池运行研究。"""
    _progress("正在初始化 Qlib 数据提供器")
    qlib.init(
        provider_uri="~/.qlib/qlib_data/cn_data",
        region=REG_CN,
    )
    _progress(f"Qlib 初始化完成，数据目录：{QLIB_DIR}")
    _progress(f"使用 Qlib 沪深300股票池 csi300，研究范围：{START_DATE} ~ {END_DATE}")
    run_research("csi300")


if __name__ == "__main__":
    main()
