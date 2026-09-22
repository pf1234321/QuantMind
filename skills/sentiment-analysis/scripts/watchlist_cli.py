#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
舆情监控列表管理工具

用法：
    python watchlist_cli.py list                     # 查看当前监控列表
    python watchlist_cli.py add 600519                # 添加股票
    python watchlist_cli.py add 600519,000001,601899  # 批量添加
    python watchlist_cli.py remove 600519             # 移除股票
    python watchlist_cli.py remove 600519,000001      # 批量移除
    python watchlist_cli.py set 002594,600519         # 覆盖整个列表
    python watchlist_cli.py clear                     # 清空列表
"""

import argparse
import json
import sys
from pathlib import Path

WATCHLIST = Path(__file__).resolve().parent.parent / "watchlist.json"  # scripts/ → sentiment-analysis/


def _load() -> dict:
    if WATCHLIST.exists():
        with open(WATCHLIST) as f:
            return json.load(f)
    return {"stocks": [], "comment": ""}


def _save(data: dict):
    WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 监控列表已更新: {', '.join(data['stocks']) or '(空)'}")


def cmd_list():
    data = _load()
    stocks = data.get("stocks", [])
    comment = data.get("comment", "")
    if not stocks:
        print("📋 监控列表为空")
    else:
        print(f"📋 当前监控 {len(stocks)} 只股票:")
        for s in stocks:
            print(f"   - {s}")
        if comment:
            print(f"   备注: {comment}")
    return stocks


def cmd_add(codes: str):
    data = _load()
    new_codes = [c.strip() for c in codes.split(",") if c.strip()]
    existing = set(data.get("stocks", []))
    added = []
    for c in new_codes:
        if c not in existing:
            existing.add(c)
            added.append(c)
    data["stocks"] = sorted(existing)
    _save(data)
    if added:
        print(f"新增: {', '.join(added)}")
    else:
        print("股票已在列表中，无变化")


def cmd_remove(codes: str):
    data = _load()
    rm_codes = set(c.strip() for c in codes.split(",") if c.strip())
    data["stocks"] = [s for s in data.get("stocks", []) if s not in rm_codes]
    _save(data)
    removed = [c for c in rm_codes if c not in data["stocks"]]
    if removed:
        print(f"已移除: {', '.join(removed)}")


def cmd_set(codes: str):
    new_stocks = sorted([c.strip() for c in codes.split(",") if c.strip()])
    data = _load()
    data["stocks"] = new_stocks
    _save(data)


def cmd_clear():
    data = _load()
    data["stocks"] = []
    _save(data)
    print("监控列表已清空")


def main():
    parser = argparse.ArgumentParser(description="舆情监控列表管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="查看当前监控列表")
    sub.add_parser("clear", help="清空列表")

    p_add = sub.add_parser("add", help="添加股票（逗号分隔）")
    p_add.add_argument("codes", help="股票代码")

    p_rm = sub.add_parser("remove", help="移除股票（逗号分隔）")
    p_rm.add_argument("codes", help="股票代码")

    p_set = sub.add_parser("set", help="覆盖整个列表")
    p_set.add_argument("codes", help="股票代码（逗号分隔）")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "add":
        cmd_add(args.codes)
    elif args.cmd == "remove":
        cmd_remove(args.codes)
    elif args.cmd == "set":
        cmd_set(args.codes)
    elif args.cmd == "clear":
        cmd_clear()


if __name__ == "__main__":
    main()
