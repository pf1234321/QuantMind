# -*- coding: utf-8 -*-
"""当前请求的链路标识上下文。"""
from contextvars import ContextVar
from typing import Optional


_request_id: ContextVar[Optional[str]] = ContextVar("quantmind_request_id", default=None)


def get_request_id() -> str:
    """返回当前请求 ID；非请求线程/任务返回短横线。"""
    return _request_id.get() or "-"


def set_request_id(request_id: str):
    """设置当前上下文并返回可用于恢复的 token。"""
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    """恢复进入当前上下文前的 request ID。"""
    _request_id.reset(token)
