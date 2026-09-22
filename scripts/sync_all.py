# -*- coding: utf-8 -*-
"""全量数据同步脚本（命令行方式，执行情况写入 sync_task_log）
用法:
  python scripts/sync_all.py              # 全量
  python scripts/sync_all.py --kline      # 仅 K线(baostock)
  python scripts/sync_all.py --sectors    # 仅板块聚合
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import scheduler  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="QuantMind 数据同步")
    parser.add_argument("--kline", action="store_true", help="同步 K线(baostock)")
    parser.add_argument("--industry", action="store_true", help="同步申万行业")
    parser.add_argument("--sectors", action="store_true", help="板块聚合重算")
    parser.add_argument("--news", action="store_true", help="同步新闻")
    parser.add_argument("--report", action="store_true", help="同步研报")
    parser.add_argument("--macro", action="store_true", help="同步宏观")
    parser.add_argument("--calendar", action="store_true", help="同步日历")
    parser.add_argument("--catalyst", action="store_true", help="同步催化剂")
    parser.add_argument("--all", action="store_true", help="全量同步")
    args = parser.parse_args()

    # 选中的任务
    picked = [
        name
        for name, flag in (
            ("industry", args.industry),
            ("kline", args.kline),
            ("sectors", args.sectors),
            ("news", args.news),
            ("report", args.report),
            ("macro", args.macro),
            ("calendar", args.calendar),
            ("catalyst", args.catalyst),
        )
        if flag
    ]
    if args.all or not picked:
        # 默认/--all 时执行全部已启用任务（顺序执行，失败容忍）
        results = scheduler.run_all(trigger="manual")
    else:
        results = {name: scheduler.run_task(name, trigger="manual") for name in picked}

    print("=" * 60)
    for name, out in results.items():
        status = out.get("status", "?")
        log_id = out.get("log_id", "-")
        detail = out.get("result") or out.get("error") or out.get("reason", "")
        print(f"[{name}] {status} log_id={log_id} {detail}")
    print("=" * 60)
    print("同步完成，执行日志已写入 sync_task_log")


if __name__ == "__main__":
    main()
