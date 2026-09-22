#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时舆情分析任务 — 抓新闻 → 情感分析 → 事件检测 → 写入数据库

用法：
    python scheduled_sentiment.py                          # 分析默认监控列表
    python scheduled_sentiment.py --stocks 002594,600519  # 指定股票
    python scheduled_sentiment.py --mode full             # 全模式（含恐慌指数 + Polymarket）
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent.parent.parent   # scripts/sentiment-analysis/skills/nanobot
SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = SKILL_DIR / "watchlist.json"


def load_watchlist() -> list:
    """从 watchlist.json 加载监控股票列表"""
    if WATCHLIST_FILE.exists():
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
            return data.get("stocks", [])
    return []


def save_watchlist(stocks: list):
    """保存监控股票列表到 watchlist.json"""
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump({
            "stocks": stocks,
            "comment": "用户自定义舆情监控股票列表"
        }, f, ensure_ascii=False, indent=2)
    print(f"[配置] 监控列表已保存到 {WATCHLIST_FILE}")

# ─── 辅助 ────────────────────────────────────

def run_cmd(cmd: list, cwd: str = None, timeout: int = 180) -> dict:
    """运行子进程并返回结果"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd or str(ROOT), timeout=timeout,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"超时 ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


def get_python():
    return str(ROOT / ".venv" / "bin" / "python")


def load_db():
    """延迟导入数据库模块"""
    sys.path.insert(0, str(SCRIPTS))
    from db_writer import SentimentDB
    return SentimentDB()


# ─── 核心流程 ────────────────────────────────

def step_fetch_news(stock: str, days: int = 3) -> dict:
    """抓新闻"""
    news_file = str(ROOT / "data" / f"{stock}_news.json")
    news_script = str(SCRIPTS / "news_fetcher.py")

    result = run_cmd([
        get_python(), news_script,
        "--stock", stock,
        "--days", str(days),
    ])

    if result["ok"] or os.path.exists(news_file):
        return {"ok": True, "file": news_file, "stdout": result["stdout"]}
    return result


def step_analyze(stock: str, news_file: str, max_news: int = 30) -> dict:
    """情感分析"""
    sentiment_script = str(SCRIPTS / "sentiment_scorer.py")
    output_dir = str(ROOT / "output")

    result = run_cmd([
        get_python(), sentiment_script,
        "--news_file", news_file,
        "--output_dir", output_dir,
        "--stock_code", stock,
        "--db",
        "--max_news", str(max_news),
    ], timeout=300)

    return result


def step_detect_events(stock: str, news_file: str) -> dict:
    """事件检测 + 入库"""
    event_script = str(SCRIPTS / "event_detector.py")
    output_dir = str(ROOT / "output")

    result = run_cmd([
        get_python(), event_script,
        "--news_file", news_file,
        "--output_dir", output_dir,
    ])

    # 读取事件结果写入 DB
    if result["ok"]:
        event_json = Path(output_dir) / f"{Path(news_file).stem}_events.json"
        if event_json.exists():
            try:
                with open(event_json) as f:
                    events_data = json.load(f)
                events = events_data if isinstance(events_data, list) else events_data.get("events", [])
                db = load_db()
                db.save_event(events)
                db.close()
            except Exception as e:
                result["stderr"] += f"\nDB write error: {e}"

    return result


def step_fear_index():
    """宏观恐慌指数（每天跑一次即可）"""
    script = str(SCRIPTS / "market_fear_index.py")

    result = run_cmd([get_python(), script, "--include_ashare"], timeout=120)
    return result


# ─── 主入口 ──────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="定时舆情分析任务 — 默认从 watchlist.json 读取监控股票",
        epilog="修改监控列表: 编辑 watchlist.json 或执行 --set-watchlist 002594,600519,000858"
    )
    parser.add_argument(
        "--stocks",
        default=None,
        help="指定股票（逗号分隔），不传则使用 watchlist.json",
    )
    parser.add_argument(
        "--set-watchlist",
        default=None,
        help="修改监控列表并退出，eg: --set-watchlist 002594,600519",
    )
    parser.add_argument(
        "--mode",
        default="quick",
        choices=["quick", "full"],
        help="quick=仅情感+事件, full=含恐慌指数（默认 quick）",
    )
    parser.add_argument("--days", type=int, default=3, help="抓取最近 N 天新闻（默认 3）")
    parser.add_argument("--max_news", type=int, default=30, help="每只股票最大分析条数（默认 30）")
    args = parser.parse_args()

    # ── 设置监控列表 ──
    if args.set_watchlist:
        stocks = [s.strip() for s in args.set_watchlist.split(",") if s.strip()]
        save_watchlist(stocks)
        print(f"监控列表已更新: {', '.join(stocks)}")
        return 0

    # ── 获取股票列表：--stocks > watchlist.json ──
    if args.stocks:
        stocks = [s.strip() for s in args.stocks.split(",") if s.strip()]
    else:
        stocks = load_watchlist()
        if not stocks:
            print("[错误] 未指定股票，请使用 --stocks 或 --set-watchlist 设置")
            return 1
    today = date.today().isoformat()

    print(f"{'='*60}")
    print(f"[定时任务] 舆情分析 - {today}")
    print(f"[监控股票] {', '.join(stocks)}")
    print(f"[模式] {args.mode}")
    print(f"{'='*60}\n")

    # 确保 data/ 和 output/ 目录存在
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "output").mkdir(exist_ok=True)

    summary = {"stocks": {}, "ok": 0, "fail": 0}

    # ── 逐只股票分析 ──
    for stock in stocks:
        print(f"\n--- [{stock}] 开始 ---")

        # ① 抓新闻
        fetch = step_fetch_news(stock, args.days)
        if not fetch["ok"] or not os.path.exists(fetch.get("file", "")):
            print(f"[{stock}] ❌ 新闻抓取失败: {fetch.get('stderr', '')}")
            summary["fail"] += 1
            continue
        print(f"[{stock}] ✅ 新闻抓取完成: {fetch['file']}")

        # ② 情感分析 + 入库
        analyze = step_analyze(stock, fetch["file"], args.max_news)
        if not analyze["ok"]:
            print(f"[{stock}] ⚠️ 情感分析失败: {analyze.get('stderr', '')[:200]}")
        else:
            print(f"[{stock}] ✅ 情感分析完成")

        # ③ 事件检测 + 入库
        events = step_detect_events(stock, fetch["file"])
        if not events["ok"]:
            print(f"[{stock}] ⚠️ 事件检测失败: {events.get('stderr', '')[:200]}")
        else:
            print(f"[{stock}] ✅ 事件检测完成")

        summary["stocks"][stock] = {
            "sentiment": analyze["ok"],
            "events": events["ok"],
        }
        summary["ok"] += 1

    # ── 宏观指标（仅 full 模式）──
    if args.mode == "full":
        print(f"\n--- [宏观] 恐慌指数 ---")
        fear = step_fear_index()
        if fear["ok"]:
            print("[宏观] ✅ 恐慌指数完成")
            summary["macro"] = "ok"
        else:
            print(f"[宏观] ⚠️ 恐慌指数失败: {fear.get('stderr', '')[:200]}")
            summary["macro"] = "fail"

    # ── 输出汇总 ──
    print(f"\n{'='*60}")
    print(f"[完成] {summary['ok']}/{len(stocks)} 只股票分析成功, {summary['fail']} 只失败")
    print(f"[输出] JSON: {ROOT}/output/ | DB: {ROOT}/data/")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"{'='*60}")

    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
