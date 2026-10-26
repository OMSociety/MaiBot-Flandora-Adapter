"""通知事件编解码：Flandora 的 ``notice`` 事件 -> 宿主 message_dict。

宿主只做类型识别（``is_notify=True``），通知文本由适配器完整格式化，前缀沿用
``[事件-xxx]`` 约定（见 ``src/chat/message_receive/bot.py`` 的 ``handle_notice_message``）。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Mapping, Optional

from ..constants import (
    FLANDORA_PLATFORM,
    NOTICE_FRIEND_RECALL,
    NOTICE_GROUP_RECALL,
    NOTICE_NOTIFY,
    NOTIFY_POKE,
)
from .segments_in import text_component


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """把任意值安全规整为只读映射。"""

    return value if isinstance(value, Mapping) else {}


def _feature_string(payload: Mapping[str, Any]) -> str:
    """事件特征串，用于幂等去重。"""

    fields = (
        str(payload.get("notice_type") or "").strip().lower(),
        str(payload.get("sub_type") or "").strip().lower(),
        str(payload.get("user_id") or "").strip(),
        str(payload.get("operator_id") or "").strip(),
        str(payload.get("group_id") or "").strip(),
        str(payload.get("message_id") or "").strip(),
        str(payload.get("target_id") or "").strip(),
    )
    return "|".join(fields)


def build_notice_dedupe_key(payload: Mapping[str, Any]) -> str:
    """通知事件的幂等键：同一事件重复投递时取到同一个值。"""

    digest = hashlib.sha1(_feature_string(payload).encode("utf-8")).hexdigest()[:12]
    return f"notice:{digest}"


def _message_id_suffix(message_id: str, known: bool) -> str:
    """撤回类通知的消息号后缀；未知时不写，避免给出假 ID。"""

    if not known or not message_id or message_id == "0":
        return ""
    return f"（message_id={message_id}）"


def build_notice_message_dict(
    payload: Mapping[str, Any],
    *,
    self_id: str,
    enable_group_recall: bool = True,
    enable_friend_recall: bool = True,
    enable_poke: bool = True,
) -> Optional[Dict[str, Any]]:
    """把 Flandora 的通知事件翻译成宿主 message_dict。

    Args:
        payload: Flandora 推送的 ``notice`` 事件。
        self_id: 机器人自身账号。
        enable_group_recall: 是否上报群消息撤回。
        enable_friend_recall: 是否上报好友撤回。
        enable_poke: 是否上报戳一戳。

    Returns:
        Optional[Dict[str, Any]]: 通知字典；类型未识别或已被配置关闭时返回 ``None``。
    """

    notice_type = str(payload.get("notice_type") or "").strip().lower()
    sub_type = str(payload.get("sub_type") or "").strip().lower()

    user_id = str(payload.get("user_id") or "").strip()
    operator_id = str(payload.get("operator_id") or "").strip() or user_id
    group_id = str(payload.get("group_id") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    message_id = str(payload.get("message_id") or "").strip()
    message_id_known = bool(payload.get("message_id_known"))

    timestamp = payload.get("time")
    if not isinstance(timestamp, (int, float)):
        timestamp = time.time()

    text = ""
    is_group_event = False

    if notice_type == NOTICE_GROUP_RECALL:
        if not enable_group_recall:
            return None
        text = (
            f"[事件-群撤回] {operator_id} 撤回了 {user_id} 的消息"
            f"{_message_id_suffix(message_id, message_id_known)}"
        )
        is_group_event = True

    elif notice_type == NOTICE_FRIEND_RECALL:
        if not enable_friend_recall:
            return None
        text = (
            f"[事件-私聊撤回] {operator_id} 撤回了 {user_id} 的消息"
            f"{_message_id_suffix(message_id, message_id_known)}"
        )

    elif notice_type == NOTICE_NOTIFY and sub_type == NOTIFY_POKE:
        if not enable_poke:
            return None
        text = f"[事件-戳一戳] {user_id} 戳了戳 {target_id or '对方'}"
        is_group_event = bool(group_id)

    else:
        return None

    if not operator_id:
        return None

    digest = hashlib.sha1(_feature_string(payload).encode("utf-8")).hexdigest()[:8]
    notice_message_id = f"flandora-notice-{int(float(timestamp) * 1000)}-{digest}"

    additional_config: Dict[str, Any] = {
        "flandora_notice_type": notice_type,
        "flandora_notice_sub_type": sub_type,
        "flandora_notice_payload": dict(payload),
    }

    message_info: Dict[str, Any] = {
        "user_info": {
            "user_id": operator_id,
            "user_nickname": operator_id,
            "user_cardname": None,
        },
        "additional_config": additional_config,
    }
    if is_group_event and group_id:
        message_info["group_info"] = {
            "group_id": group_id,
            "group_name": str(payload.get("group_name") or "").strip(),
        }

    return {
        "message_id": notice_message_id,
        "timestamp": str(float(timestamp)),
        "platform": FLANDORA_PLATFORM,
        "account_id": str(self_id or "").strip(),
        "scope": None,
        "message_info": message_info,
        "raw_message": [text_component(text)],
        "is_mentioned": False,
        "is_at": False,
        "is_emoji": False,
        "is_picture": False,
        "is_command": False,
        "is_notify": True,
        "session_id": "",
        "processed_plain_text": text,
    }
