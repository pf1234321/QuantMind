# -*- coding: utf-8 -*-
"""LLM 客户端（Qwen / DashScope OpenAI 兼容模式）

统一封装 Qwen 调用逻辑，供 diagnosis_events.py 直接使用。
依赖环境变量：
- DASHSCOPE_API_KEY
- QWEN_MODEL (可选，默认 qwen-max)
"""

import os
from openai import OpenAI

def call_qwen(prompt: str) -> str:
    """调用 Qwen（OpenAI 兼容模式），返回文本内容"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 DASHSCOPE_API_KEY，请在 .env 中配置")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    completion = client.chat.completions.create(
        model=os.getenv("QWEN_MODEL", "qwen-max"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    return completion.choices[0].message.content.strip()
