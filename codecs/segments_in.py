"""入站段翻译：OneBot v11 段 -> 宿主消息组件。

宿主侧的组件格式与 OneBot 不同（见 ``src/plugin_runtime/host/message_utils.py`` 的
``_component_from_dict``）：``text`` 的 ``data`` 是裸字符串而不是字典，二进制类组件要求
``hash`` + ``binary_data_base64``，``at`` / ``reply`` 用宿主自己的字段名。这里逐项翻译。
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse

from ..constants import (
    BASE64_URI_PREFIX,
    COMPONENT_AT,
    COMPONENT_FILE,
    COMPONENT_IMAGE,
    COMPONENT_REPLY,
    COMPONENT_TEXT,
    COMPONENT_VOICE,
    FILE_URI_PREFIX,
    HTTP_PREFIXES,
    SEGMENT_AT,
    SEGMENT_EMOJI,
    SEGMENT_FACE,
    SEGMENT_FILE,
    SEGMENT_FORWARD,
    SEGMENT_IMAGE,
    SEGMENT_NODE,
    SEGMENT_NODES,
    SEGMENT_RECORD,
    SEGMENT_REPLY,
    SEGMENT_TEXT,
    SEGMENT_VIDEO,
)

PLACEHOLDER_PICTURE = "[图片]"
PLACEHOLDER_VOICE = "[语音]"
PLACEHOLDER_VIDEO = "[视频]"
PLACEHOLDER_REPLY = "[回复]"
PLACEHOLDER_FORWARD = "[合并转发]"


@dataclass
class InboundSegments:
    """入站段翻译结果。"""

    components: List[Dict[str, Any]] = field(default_factory=list)
    at_bot: bool = False
    has_picture: bool = False
    has_emoji: bool = False


def segment_type(segment: Mapping[str, Any]) -> str:
    """取段类型（小写）。"""

    return str(segment.get("type") or "").strip().lower()


def segment_data(segment: Mapping[str, Any]) -> Mapping[str, Any]:
    """取段数据；``data`` 是裸字符串时按文本段兜底。"""

    data = segment.get("data")
    if isinstance(data, Mapping):
        return data
    if isinstance(data, str):
        return {"text": data}
    return {}


def text_component(text: str) -> Dict[str, Any]:
    """构造宿主文本组件。"""

    return {"type": COMPONENT_TEXT, "data": str(text)}


def at_component(target_user_id: str, nickname: Optional[str] = None) -> Dict[str, Any]:
    """构造宿主 at 组件。"""

    return {
        "type": COMPONENT_AT,
        "data": {
            "target_user_id": str(target_user_id),
            "target_user_nickname": nickname or None,
            "target_user_cardname": None,
        },
    }


def resolve_local_path(reference: str) -> Optional[Path]:
    """把 ``file://`` URI 或本机路径解析为 :class:`Path`；http(s) 与 base64 返回 ``None``。"""

    text = str(reference or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith(HTTP_PREFIXES) or lowered.startswith(BASE64_URI_PREFIX):
        return None
    if text.startswith(FILE_URI_PREFIX):
        parsed = urlparse(text)
        raw_path = unquote(parsed.path or "")
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{raw_path}"
        # Windows 下 file:///D:/x 解析出的路径是 /D:/x，去掉多余的前导斜杠
        if len(raw_path) > 2 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        return Path(raw_path) if raw_path else None
    return Path(text)


def read_reference_bytes(reference: str) -> bytes:
    """读取段里引用的文件内容。

    ``base64://`` 直接解码，``file://`` 与本机路径读盘；``http(s)://`` 不取件。

    Returns:
        bytes: 读到的字节；引用形态不认识或读取失败时返回空字节串。
    """

    text = str(reference or "").strip()
    if not text:
        return b""
    if text.startswith(BASE64_URI_PREFIX):
        encoded = text[len(BASE64_URI_PREFIX) :].strip()
        try:
            return base64.b64decode(encoded, validate=False)
        except (ValueError, TypeError):
            return b""
    lowered = text.lower()
    if lowered.startswith(HTTP_PREFIXES):
        return b""
    path = resolve_local_path(text)
    if path is None:
        return b""
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _binary_component(
    component_type: str,
    data: Mapping[str, Any],
    *,
    attachment_max_bytes: int,
    placeholder: str,
    logger: Any,
) -> Dict[str, Any]:
    """构造二进制类组件（image / voice）；内容取不到时退化为占位文本。

    宿主把段里的 ``data`` 当作人读的文本描述：留空时才会拿二进制字节去识图，
    带上引用会让识图被跳过，整幅图片的 base64 于是进了聊天记录。
    """

    reference = str(data.get("file") or data.get("url") or data.get("path") or "").strip()
    if not reference:
        return text_component(placeholder)

    payload = read_reference_bytes(reference)
    if not payload:
        logger.warning(f"{placeholder} 的内容读不到，已退化为占位文本：{reference}")
        return text_component(placeholder)

    if len(payload) > attachment_max_bytes:
        logger.warning(
            f"{placeholder} 原始 {len(payload)} 字节超过内联上限 "
            f"{attachment_max_bytes} 字节，已退化为占位文本"
        )
        return text_component(f"{placeholder}（{len(payload)} 字节，超过内联上限）")

    declared_hash = str(data.get("hash") or "").strip()
    return {
        "type": component_type,
        "data": "",
        "hash": declared_hash or hashlib.sha256(payload).hexdigest(),
        "binary_data_base64": base64.b64encode(payload).decode("ascii"),
    }


def _file_component(
    data: Mapping[str, Any],
    *,
    attachment_max_bytes: int,
    logger: Any,
) -> Dict[str, Any]:
    """构造文件组件；读不到或超限时退化为占位文本。"""

    reference = str(data.get("file") or data.get("url") or "").strip()
    name = str(data.get("name") or "").strip()
    label = f"[文件] {name}" if name else "[文件]"

    if not reference:
        return text_component(label)

    payload = read_reference_bytes(reference)
    if not payload:
        logger.warning(f"文件内容读不到，已退化为占位文本：{reference}")
        return text_component(label)

    if len(payload) > attachment_max_bytes:
        logger.warning(
            f"文件原始 {len(payload)} 字节超过内联上限 "
            f"{attachment_max_bytes} 字节，已退化为占位文本"
        )
        return text_component(f"{label}（{len(payload)} 字节，超过内联上限）")

    file_payload: Dict[str, Any] = {}
    if name:
        file_payload["name"] = name
    elif resolve_local_path(reference) is not None:
        file_payload["name"] = resolve_local_path(reference).name  # type: ignore[union-attr]
    file_payload["size"] = str(len(payload))
    file_payload["base64"] = base64.b64encode(payload).decode("ascii")
    return {"type": COMPONENT_FILE, "data": file_payload}


def build_components(
    segments: Sequence[Any],
    *,
    self_id: str,
    attachment_max_bytes: int,
    logger: Any,
) -> InboundSegments:
    """把 OneBot 段列表翻译成宿主组件列表。

    Args:
        segments: OneBot v11 数组格式的段列表。
        self_id: 机器人自身账号，用于判断是否 @ 了自己。
        attachment_max_bytes: 单个附件内联上限。
        logger: 插件日志对象。

    Returns:
        InboundSegments: 组件列表与 @ / 图片 / 表情标记。
    """

    result = InboundSegments()
    normalized_self = str(self_id or "").strip()

    for raw_segment in segments:
        if not isinstance(raw_segment, Mapping):
            logger.debug(f"入站段不是映射，已跳过：{type(raw_segment).__name__}")
            continue
        kind = segment_type(raw_segment)
        data = segment_data(raw_segment)

        if kind == SEGMENT_TEXT:
            text = data.get("text")
            if text is None:
                text = data.get("content")
            text = "" if text is None else str(text)
            if text:
                result.components.append(text_component(text))
            else:
                logger.debug("入站文本段是空串，已跳过")
            continue

        if kind == SEGMENT_AT:
            target = str(data.get("qq") or "").strip()
            nickname = str(data.get("name") or "").strip()
            if not target:
                # 只有名字的 @（Flandora 在拿不到 id 时这样发），退化成文本
                result.components.append(text_component(f"@{nickname}" if nickname else "@"))
                continue
            if target.lower() == "all":
                result.components.append(text_component("@全体成员"))
                continue
            if normalized_self and target == normalized_self:
                result.at_bot = True
            result.components.append(at_component(target, nickname or None))
            continue

        if kind == SEGMENT_IMAGE or kind == SEGMENT_EMOJI:
            result.components.append(
                _binary_component(
                    COMPONENT_IMAGE,
                    data,
                    attachment_max_bytes=attachment_max_bytes,
                    placeholder=PLACEHOLDER_PICTURE,
                    logger=logger,
                )
            )
            result.has_picture = True
            continue

        if kind == SEGMENT_FACE:
            face_id = str(data.get("id") or "").strip()
            result.components.append(text_component(f"[表情 {face_id}]" if face_id else "[表情]"))
            result.has_emoji = True
            continue

        if kind == SEGMENT_RECORD:
            result.components.append(
                _binary_component(
                    COMPONENT_VOICE,
                    data,
                    attachment_max_bytes=attachment_max_bytes,
                    placeholder=PLACEHOLDER_VOICE,
                    logger=logger,
                )
            )
            continue

        if kind == SEGMENT_VIDEO:
            result.components.append(text_component(PLACEHOLDER_VIDEO))
            continue

        if kind == SEGMENT_FILE:
            result.components.append(
                _file_component(data, attachment_max_bytes=attachment_max_bytes, logger=logger)
            )
            continue

        if kind == SEGMENT_REPLY:
            target_message_id = str(data.get("id") or "").strip()
            if target_message_id and target_message_id != "0":
                result.components.append(
                    {
                        "type": COMPONENT_REPLY,
                        "data": {"target_message_id": target_message_id},
                    }
                )
            else:
                result.components.append(text_component(PLACEHOLDER_REPLY))
            continue

        if kind in (SEGMENT_FORWARD, SEGMENT_NODE, SEGMENT_NODES):
            result.components.append(text_component(PLACEHOLDER_FORWARD))
            continue

        logger.warning(f"未识别的入站段类型：{kind or '<空>'}")
        result.components.append(text_component(f"[未识别的段 {kind or '未知'}]"))

    return result


def build_plain_text(components: Sequence[Mapping[str, Any]]) -> str:
    """按宿主可读的方式拼出纯文本。"""

    parts: List[str] = []
    for component in components:
        kind = str(component.get("type") or "")
        data = component.get("data")
        if kind == COMPONENT_TEXT:
            parts.append(str(data or ""))
        elif kind == COMPONENT_AT:
            info = data if isinstance(data, Mapping) else {}
            label = str(
                info.get("target_user_nickname") or info.get("target_user_id") or ""
            ).strip()
            parts.append(f"@{label}")
        elif kind == COMPONENT_IMAGE:
            parts.append(PLACEHOLDER_PICTURE)
        elif kind == COMPONENT_VOICE:
            parts.append(PLACEHOLDER_VOICE)
        elif kind == COMPONENT_FILE:
            info = data if isinstance(data, Mapping) else {}
            name = str(info.get("name") or "").strip()
            parts.append(f"[文件] {name}" if name else "[文件]")
        elif kind == COMPONENT_REPLY:
            parts.append(PLACEHOLDER_REPLY)
    return "".join(parts).strip()
