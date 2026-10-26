"""适配器调试日志器。

只承担一个职责：按配置开关决定是否把入站原始事件写进日志，
并对超长载荷做截断，避免一条事件刷满日志文件。
"""

from __future__ import annotations

import json
from typing import Any

_MAX_PREVIEW_CHARS = 2000


class FlandoraDebugLogger:
    """按开关输出原始载荷的调试日志器。"""

    def __init__(self, logger: Any, enabled: bool = False) -> None:
        """初始化调试日志器。

        Args:
            logger: 插件日志对象。
            enabled: 是否开启原始事件记录。
        """

        self._logger = logger
        self._enabled = bool(enabled)

    def set_enabled(self, enabled: bool) -> None:
        """更新开关状态。"""

        self._enabled = bool(enabled)

    def raw_event(self, payload: Any) -> None:
        """记录一条入站原始事件。"""

        if not self._enabled:
            return

        try:
            text = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            text = repr(payload)

        if len(text) > _MAX_PREVIEW_CHARS:
            text = f"{text[:_MAX_PREVIEW_CHARS]}...(已截断，原文共 {len(text)} 字符)"

        self._logger.info(f"[Flandora] 原始事件 {text}")
