# -*- coding: utf-8 -*-
"""国泰君安"五步法"公告/财报 RAG 分析

五步法: 信息差 -> 逻辑差 -> 预期差 -> 催化剂 -> 结论+风险闭环
每一步先按专属检索词从 Chroma 向量库召回公告片段，再交给 LLM 结构化分析，
上一步结论作为下一步的输入，最后汇总为完整分析报告。

用法:
  python -m app.services.rag_analysis --code 600519 --name 贵州茅台
"""
import argparse
import logging
from typing import Any

from app.config import settings
from app.services.rag_vector import query_announcements

logger = logging.getLogger(__name__)

# ================================================================ Prompt 模板
INFORMATION_GAP_PROMPT = """你是一位资深投资分析师，正在分析{stock_name}({stock_code})的公告与财报数据。

任务：寻找"信息差"——市场尚未充分关注或被忽视的关键信息。

请基于以下从公告中检索到的数据，完成以下分析：

1. 【隐藏亮点】：找出被市场忽视的正面信息
   - 业绩预告/快报中的超预期数字、新业务/新产品增长信号
   - 增持、回购、股权激励、重大合同等事件

2. 【隐藏风险】：找出被市场忽视的负面信息
   - 减持、解禁、立案、处罚、退市风险、破产重整等
   - 应收账款/存货异常、现金流与利润背离

3. 【关键数据】：提取最能体现信息差的 3-5 个核心数据点

公告相关数据：
{context}

请用结构化格式输出，每个要点附上具体数据支撑。"""

LOGIC_GAP_PROMPT = """你是一位资深投资分析师，正在分析{stock_name}({stock_code})。

基于上一步发现的信息差：
{previous_analysis}

任务：寻找"逻辑差"——市场对数据的解读可能存在哪些推理错误。

请完成以下分析：
1. 【常见误读】：市场最常见的错误认知是什么（如把一次性减值当持续性亏损）？
2. 【因果重构】：基于公告数据重新构建正确的因果逻辑链（数据A -> 导致B -> 实际影响是C而非市场认为的D）
3. 【预判修正】：市场基于错误逻辑可能做出的错误预判是什么？正确的预判应该是什么？

补充公告数据：
{context}

请用清晰的逻辑链条呈现，标注每个推理步骤的数据依据。"""

EXPECTATION_GAP_PROMPT = """你是一位资深投资分析师，正在分析{stock_name}({stock_code})。

基于前两步的分析：
{previous_analysis}

任务：寻找"预期差"——市场一致预期与实际/合理预期之间的偏离。

请完成以下分析：
1. 【核心指标对比】：
   | 指标 | 市场一致预期 | 公告实际/合理估计 | 偏离幅度 |
   |------|------------|----------------|---------|
   （营收增速、净利润增速、毛利率、ROE 等）

2. 【预期差的驱动因素】：哪些因素导致？一次性还是可持续？
3. 【预期差的方向】：正向/负向/净方向与强度判断

补充公告数据（关注业绩预告、经营目标、同比变化）：
{context}

请尽量定量分析，用数据说话。缺少一致预期时基于行业经验合理估计并注明。"""

CATALYST_PROMPT = """你是一位资深投资分析师，正在分析{stock_name}({stock_code})。

基于前三步的分析：
{previous_analysis}

任务：识别"催化剂"——可能触发市场重新评估该公司价值的事件。

请完成以下分析：
1. 【短期催化剂】(1-3个月)：即将发布的财报/业绩预告、重大合同、增持/回购计划
2. 【中期催化剂】(3-12个月)：新业务放量、并购重组、股权激励落地
3. 【潜在负面催化剂】：可能引发股价下跌的风险事件（解禁、减持、监管）
4. 【催化剂时间表】：按时间线排列最可能发生的催化剂

补充公告数据（关注未来展望、重大事项、分红回购）：
{context}

请给出具体的事件描述和预计发生时间窗口。"""

CONCLUSION_PROMPT = """你是一位资深投资分析师，正在为{stock_name}({stock_code})撰写投资结论。

前四步分析结果：
{previous_analysis}

任务：综合前四步，给出最终投资结论。

1. 【核心观点】(一句话总结)
2. 【投资逻辑】(3-5个要点，串联信息差/逻辑差/预期差/催化剂)
3. 【投资评级】：强烈推荐 / 推荐 / 中性 / 回避，附依据
4. 【关键假设与风险】：结论成立的前提；假设被证伪的最大风险
5. 【关注指标】：应持续跟踪的 3-5 个关键指标

补充公告数据：
{context}

注意：投资建议仅供参考，不构成投资决策依据，需附免责声明。"""

FIVE_STEP_CONFIG: list[dict[str, Any]] = [
    {"step": 1, "name": "信息差", "name_en": "information_gap", "prompt": INFORMATION_GAP_PROMPT,
     "rag_query": "业绩预告 快报 营收 净利润 现金流 毛利率 应收账款 存货 减值 关联交易 非经常性损益 减持 解禁 回购 增持"},
    {"step": 2, "name": "逻辑差", "name_en": "logic_gap", "prompt": LOGIC_GAP_PROMPT,
     "rag_query": "业务分析 竞争格局 成本结构 毛利率变化原因 收入构成 增长驱动力 业绩变动原因"},
    {"step": 3, "name": "预期差", "name_en": "expectation_gap", "prompt": EXPECTATION_GAP_PROMPT,
     "rag_query": "同比 环比 增长 下降 业绩预告 经营目标 区间 上限 下限 ROE 毛利率"},
    {"step": 4, "name": "催化剂", "name_en": "catalyst", "prompt": CATALYST_PROMPT,
     "rag_query": "未来展望 发展规划 重大合同 资产重组 股权激励 分红 回购 增持 政策影响 时间表"},
    {"step": 5, "name": "结论", "name_en": "conclusion", "prompt": CONCLUSION_PROMPT,
     "rag_query": "公司概况 核心竞争力 行业地位 风险因素 股东 股本 市值"},
]


# ================================================================ LLM 调用
def _llm_chat(user_prompt: str, system: str = "你是一位严谨的资深投资分析师") -> str:
    """调用 DashScope qwen（OpenAI 兼容端点）

    - 显式禁用环境/系统代理（DashScope 为国内服务，直连更快更稳）
    - 设置总超时 180s（connect 20s），避免长请求无限卡死
    - max_tokens 限制输出长度，防止五步法长文无限生成
    """
    import httpx
    from openai import OpenAI

    key = settings.DASHSCOPE_API_KEY
    if not key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，请在 .env 中配置")
    client = OpenAI(
        api_key=key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=httpx.Timeout(180.0, connect=20.0),
        http_client=httpx.Client(trust_env=False),  # 不走系统代理
    )
    resp = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        temperature=0.3,
        max_tokens=2000,
    )
    return resp.choices[0].message.content.strip()


def _format_context(hits: list[dict], max_len: int = 4000) -> str:
    """把 RAG 命中片段格式化为上下文（带来源标注）"""
    parts = []
    used = 0
    for h in hits:
        chunk = (h.get("chunk") or "").strip()
        if not chunk:
            continue
        tag = f"[{h.get('ann_date')}]{h.get('ann_title')}({h.get('stock_code')} {h.get('stock_name')}, 相关度{h.get('score')})"
        piece = f"{tag}\n{chunk}"
        if used + len(piece) > max_len:
            break
        parts.append(piece)
        used += len(piece)
    return "\n\n".join(parts) or "(无相关公告命中)"


# ================================================================ 五步法
def run_five_step_analysis(
    stock_code: str,
    stock_name: str | None = None,
    *,
    top_k: int = 8,
    only_important: bool = False,
    end_date: str | None = None,
) -> dict[str, Any]:
    """对某只股票执行五步法分析

    Returns:
      {stock_code, stock_name, steps: [...], report: markdown}
      steps[i] = {step, name, rag_query, hits, analysis}
    """
    code = str(stock_code).split(".")[0]
    name = stock_name or code

    steps_out: list[dict[str, Any]] = []
    previous = ""
    report_parts = [f"# {name}({code}) 国泰君安五步法分析报告\n"]

    for cfg in FIVE_STEP_CONFIG:
        logger.info("[五步法] Step%d %s: %s", cfg["step"], cfg["name"], cfg["rag_query"][:40])
        hits = query_announcements(
            cfg["rag_query"], stock_code=code,
            only_important=only_important, top_k=top_k, end_date=end_date,
        )
        context = _format_context(hits)
        prompt = cfg["prompt"].format(
            stock_name=name, stock_code=code,
            previous_analysis=previous or "(此为第一步，暂无上一步分析)",
            context=context,
        )
        try:
            analysis = _llm_chat(prompt)
        except Exception as exc:  # noqa: BLE001 单步失败不阻塞
            logger.error("[五步法] Step%d %s 失败: %s", cfg["step"], cfg["name"], exc)
            analysis = f"(分析失败: {exc})"

        steps_out.append({
            "step": cfg["step"], "name": cfg["name"], "name_en": cfg["name_en"],
            "rag_query": cfg["rag_query"], "hits": hits, "analysis": analysis,
        })
        previous = analysis
        report_parts.append(f"\n---\n\n## Step{cfg['step']} {cfg['name']}\n\n{analysis}")

    report_parts.append("\n\n---\n*本报告由 AI 基于公告 RAG 自动生成，仅供参考，不构成投资建议。*")
    return {
        "stock_code": code, "stock_name": name,
        "steps": steps_out, "report": "\n".join(report_parts),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="国泰君安五步法公告分析")
    parser.add_argument("--code", required=True, help="股票代码")
    parser.add_argument("--name", default=None, help="股票名称")
    parser.add_argument("--topk", type=int, default=8, help="每步检索切块数")
    args = parser.parse_args()

    result = run_five_step_analysis(args.code, args.name, top_k=args.topk)
    print(result["report"])
