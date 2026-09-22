import argparse
from .adapter import load_course_adapter
from .runner import scan_atr_exit_mult
from app.strategy.atr_chan import build_internal_adapter


def main() -> None:
    parser = argparse.ArgumentParser(description="ATR 跟踪止损参数回测验证")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--course-module", help="显式指定外部课程策略模块路径")
    source.add_argument("--internal-chan", action="store_true", help="使用 QuantMind 内部缠论 ATR 策略")
    parser.add_argument("--stock-code", default="300750")
    parser.add_argument("--stock-codes", help="逗号分隔的股票代码；当前 CLI 逐只运行并输出单股票结果")
    parser.add_argument("--start-date", default="2015-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--range-start", type=float)
    parser.add_argument("--range-end", type=float)
    parser.add_argument("--step", type=float)
    parser.add_argument("--output-dir", default="data/backtest/atr_scan")
    args = parser.parse_args()
    stock_code = (args.stock_codes.split(",")[0].strip() if args.stock_codes else args.stock_code)
    adapter = load_course_adapter(args.course_module) if args.course_module else build_internal_adapter()
    result = scan_atr_exit_mult(stock_code=stock_code, start_date=args.start_date, end_date=args.end_date, range_start=args.range_start, range_end=args.range_end, step=args.step, output_dir=args.output_dir, adapter=adapter)
    print(result.summary.to_string(index=False))
    print(result.report["warning"] or "未检测到前视风险")


if __name__ == "__main__":
    main()
