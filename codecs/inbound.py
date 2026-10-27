"""入站消息编解码：Flandora 的 ``message`` 事件 -> 宿主 message_dict。

宿主只认少数几个字段（见 ``src/plugin_runtime/host/message_utils.py`` 的
``_build_session_message_from_dict``），必需 ``message_id`` / ``platform`` /
``message_info`` / ``raw_message`` 四项，其余都有默认值。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping

from ..constants import FLANDORA_PLATFORM
from .segments_in import (
    InboundSegments,
    build_components,
    build_plain_text,
    text_component,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """把任意值安全规整为只读映射。"""

    return value if isinstance(value, Mapping) else {}


def build_inbound_segments(
    payload: Mapping[str, Any],
    *,
    self_id: str,
    attachment_max_bytes: int,
    logger: Any,
) -> InboundSegments:
    """把事件里的 ``message`` 段翻译成宿主组件。

    段列表缺失或为空时，退回事件自带的 ``raw_message``（CQ 串）当纯文本；
    两者都拿不到内容时返回空组件列表。
    """

    segments = payload.get("message")
    if not isinstance(segments, list):
        segments = []

    built = build_components(
        segments,
        self_id=self_id,
        attachment_max_bytes=attachment_max_bytes,
        logger=logger,
    )
    if built.components:
        return built

    raw_text = str(payload.get("raw_message") or "").strip()
    if raw_text:
        built.components.append(text_component(raw_text))
    return built


def build_message_dict(
    payload: Mapping[str, Any],
    *,
    self_id: str,
    attachment_max_bytes: int,
    logger: Any,
) -> Dict[str, Any]:
    """把 Flandora 的消息事件翻译成宿主 message_dict。

    Args:
        payload: Flandora 推送的 ``message`` 事件。
        self_id: 机器人自身账号。
        attachment_max_bytes: 单个附件内联上限。
        logger: 插件日志对象。

    Returns:
        Dict[str, Any]: 可直接交给 ``ctx.gateway.route_message`` 的字典。

    Raises:
        ValueError: 消息号或发送者缺失时（这类载荷无法引用、去重与撤回，不合成假 ID）。
    """

    message_id = str(payload.get("message_id") or "").strip()
    if not message_id:
        raise ValueError("入站消息缺少 message_id")

    message_type = str(payload.get("message_type") or "").strip().lower()
    is_group_chat = message_type == "group"
    group_id = str(payload.get("group_id") or "").strip()
    group_name = str(payload.get("group_name") or "").strip()

    sender = _as_mapping(payload.get("sender"))
    sender_user_id = str(payload.get("user_id") or sender.get("user_id") or "").strip()
    if not sender_user_id:
        raise ValueError("入站消息缺少 user_id")

    user_nickname = str(sender.get("nickname") or sender_user_id).strip() or sender_user_id
    user_cardname = str(sender.get("card") or "").strip() or None

    built = build_inbound_segments(
        payload,
        self_id=self_id,
        attachment_max_bytes=attachment_max_bytes,
        logger=logger,
    )
    raw_message: List[Dict[str, Any]] = built.components
    plain_text = build_plain_text(raw_message)

    timestamp = payload.get("time")
    if not isinstance(timestamp, (int, float)):
        timestamp = time.time()

    # Flandora 在群消息上如实标记 is_mentioned；段里 @ 到自身也算一次
    declared_mentioned = bool(payload.get("is_mentioned"))
    at_bot = bool(built.at_bot or declared_mentioned)

    additional_config: Dict[str, Any] = {
        "at_bot": at_bot,
        "flandora_wxid": str(sender.get("wxid") or "").strip(),
        "flandora_group_wxid": str(payload.get("group_wxid") or "").strip(),
    }

    message_info: Dict[str, Any] = {
        "user_info": {
            "user_id": sender_user_id,
            "user_nickname": user_nickname,
            "user_cardname": user_cardname,
        },
        "additional_config": additional_config,
    }
    if is_group_chat and group_id:
        message_info["group_info"] = {"group_id": group_id, "group_name": group_name}

    return {
        "message_id": message_id,
        "timestamp": str(float(timestamp)),
        "platform": FLANDORA_PLATFORM,
        "account_id": str(self_id or "").strip(),
        "scope": None,
        "message_info": message_info,
        "raw_message": raw_message,
        "is_mentioned": at_bot,
        "is_at": at_bot,
        "is_emoji": built.has_emoji,
        "is_picture": built.has_picture,
        "is_command": plain_text.startswith("/"),
        "is_notify": False,
        "session_id": "",
        "processed_plain_text": plain_text,
    }
