"""出站消息编解码：宿主 message -> Flandora 动作调用。

宿主把要发的消息交给我们时，``message_info`` 里带着会话归属（群消息有 ``group_info``，
私聊的目标号由 ``send_service`` 写入 ``additional_config.platform_io_target_user_id``）；
据此挑 ``send_group_msg`` 或 ``send_private_msg``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .segments_out import build_outbound_segments

ACTION_SEND_GROUP = "send_group_msg"
ACTION_SEND_PRIVATE = "send_private_msg"


@dataclass
class OutboundRequest:
    """一次出站发送的完整描述。"""

    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    dropped: List[str] = field(default_factory=list)

    @property
    def segments(self) -> List[Dict[str, Any]]:
        """本次要发送的段列表。"""

        message = self.params.get("message")
        return list(message) if isinstance(message, list) else []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """把任意值安全规整为只读映射。"""

    return value if isinstance(value, Mapping) else {}


def _first_non_empty(*values: Any) -> str:
    """按序返回第一个非空字符串。"""

    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def resolve_target(
    message: Mapping[str, Any],
    route: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    """解析出站目标。

    取值顺序对齐宿主写入的位置：群聊优先 ``group_info.group_id``，私聊优先
    ``additional_config.platform_io_target_user_id``（由 ``send_service`` 写入）。

    Args:
        message: 宿主下发的消息字典。
        route: 宿主附带的路由信息。

    Returns:
        Optional[Dict[str, str]]: ``{"kind": "group"|"private", "id": "..."}``；
            解析不出返回 ``None``。
    """

    message_info = _as_mapping(message.get("message_info"))
    group_info = _as_mapping(message_info.get("group_info"))
    user_info = _as_mapping(message_info.get("user_info"))
    additional_config = _as_mapping(message_info.get("additional_config"))
    route_info = _as_mapping(route)

    group_id = _first_non_empty(
        group_info.get("group_id"),
        additional_config.get("platform_io_target_group_id"),
        route_info.get("group_id"),
        route_info.get("target_group_id"),
    )
    if group_id:
        return {"kind": "group", "id": group_id}

    user_id = _first_non_empty(
        additional_config.get("platform_io_target_user_id"),
        additional_config.get("target_user_id"),
        route_info.get("user_id"),
        route_info.get("target_user_id"),
        user_info.get("user_id"),
    )
    if user_id:
        return {"kind": "private", "id": user_id}

    return None


def _numeric_id(raw_id: str, *, kind: str) -> int:
    """把 Flandora 的会话 ID 转成整数。

    Flandora 的 ``user_id`` / ``group_id`` 是它自己分配的正整数；喂 wxid 或
    其它字符串进去会被回 ``1406``，所以在本地就拦下来并把原因说清楚。
    """

    text = str(raw_id or "").strip()
    if not text.isdigit():
        raise ValueError(
            f"出站目标的 {kind} 不是 Flandora 分配的数字 ID：{text or '<空>'}；"
            "请使用事件里的整数 ID（wxid 不能直接当 ID 发送）"
        )
    return int(text)


def build_outbound_request(
    message: Mapping[str, Any],
    *,
    logger: Any,
    route: Optional[Mapping[str, Any]] = None,
    self_id: str = "",
) -> OutboundRequest:
    """把宿主消息字典翻译成一次 Flandora 动作调用。

    Args:
        message: 宿主下发的消息字典（``_session_message_to_dict`` 的输出）。
        logger: 插件日志对象。
        route: 宿主附带的路由信息。
        self_id: 机器人自身账号，供段翻译参考。

    Returns:
        OutboundRequest: 动作名、参数与被降级/跳过的段说明。

    Raises:
        ValueError: 解析不出目标、目标不是数字 ID，或没有可发送的段时。
    """

    target = resolve_target(message, route)
    if target is None:
        raise ValueError("出站消息缺少会话归属（既没有 group_id 也没有 user_id）")

    components = message.get("raw_message")
    if not isinstance(components, Sequence) or isinstance(components, (str, bytes)):
        components = []

    built = build_outbound_segments(components, logger=logger, self_id=self_id)

    if not built.segments:
        detail = "、".join(built.dropped) if built.dropped else "无可用段"
        raise ValueError(f"出站消息没有可发送的段（{detail}）")

    if built.dropped:
        logger.debug(f"出站消息降级或跳过了 {len(built.dropped)} 个段：{'、'.join(built.dropped)}")

    if target["kind"] == "group":
        action = ACTION_SEND_GROUP
        params: Dict[str, Any] = {
            "group_id": _numeric_id(target["id"], kind="group_id"),
            "message": built.segments,
        }
    else:
        action = ACTION_SEND_PRIVATE
        params = {
            "user_id": _numeric_id(target["id"], kind="user_id"),
            "message": built.segments,
        }

    return OutboundRequest(action=action, params=params, dropped=built.dropped)
