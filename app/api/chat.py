# -*- coding: utf-8 -*-
"""面向前端的 nanobot 股票分析对话接口。"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["AI 对话分析"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(..., min_length=1, max_length=128)


class ChatResponse(BaseModel):
    content: str
    session_id: str
    provider: str


def _nanobot_root() -> Path:
    configured = os.getenv("NANOBOT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("/Users/Shared/学习视频教程/JK-AI 量化交易训练营/08.第八周/资料2/课程代码-20260408/nanobot").resolve()


def _build_runtime_config(root: Path) -> Path:
    """Create a temporary nanobot config using QuantMind's model settings."""
    source = root / "config.json"
    if not source.exists():
        raise RuntimeError(f"nanobot 配置不存在：{source}")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少环境变量 DASHSCOPE_API_KEY，请在 QuantMind/.env 中配置")
    config = json.loads(source.read_text(encoding="utf-8"))
    defaults = config.setdefault("agents", {}).setdefault("defaults", {})
    defaults["model"] = settings.LLM_MODEL.strip() or "qwen-plus"
    defaults["provider"] = "dashscope"
    defaults.pop("model_preset", None)
    config["providers"] = {
        "dashscope": {
            "api_key": settings.DASHSCOPE_API_KEY.strip(),
            "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }
    }
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", prefix="quantmind-nanobot-", delete=False
    )
    try:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        return Path(handle.name)
    finally:
        handle.close()


def _load_nanobot() -> Any:
    root = _nanobot_root()
    package_root = root / "vendor" / "nanobot"
    if not (package_root / "nanobot").exists():
        raise RuntimeError(f"nanobot 包路径不存在：{package_root}")
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from nanobot.nanobot import Nanobot  # type: ignore[missing-import]

    config_path = _build_runtime_config(root)
    workspace = Path(__file__).resolve().parents[2]
    try:
        return Nanobot.from_config(config_path, workspace=workspace)
    finally:
        config_path.unlink(missing_ok=True)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")
    try:
        bot = _load_nanobot()
        result = await bot.run(message, session_key=f"quantmind:{request.session_id}")
        logger.info("chat_completed session_id=%s provider=dashscope model=%s", request.session_id, settings.LLM_MODEL)
        return ChatResponse(content=result.content, session_id=request.session_id, provider="dashscope")
    except Exception as exc:
        logger.exception("chat_failed session_id=%s message_length=%s", request.session_id, len(message))
        raise HTTPException(status_code=503, detail=f"AI 对话服务暂不可用：{exc}") from exc
    