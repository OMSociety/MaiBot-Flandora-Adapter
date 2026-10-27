"""出站段翻译：宿主消息组件 -> OneBot v11 段。

Flandora 只接受本机路径、``file://`` 与 ``base64://`` 三种引用，http(s) 一律不代下，
所以这里只做引用形式的搬运：拿不到可用引用的段会降级或跳过，并如实登记到 ``dropped``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from ..constants import (
    BASE64_URI_PREFIX,
    COMPONENT_AT,
    COMPONENT_EMOJI,
    COMPONENT_FILE,
    COMPONENT_FORWARD,
    COMPONENT_IMAGE,
    COMPONENT_REPLY,
    COMPONENT_TEXT,
    COMPONENT_VOICE,
    HTTP_PREFIXES,
)

PLACEHOLDER_PICTURE = "[图片]"
PLACEHOLDER_VOICE = "[语音]"


@dataclass
class OutboundSegments:
    """出站段翻译结果。"""

    segments: List[Dict[str, Any]] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """把任意值安全规整为只读映射。"""

    return value if isinstance(value, Mapping) else {}


def text_segment(text: str) -> Dict[str, Any]:
    """构造文本段。"""

    return {"type": "text", "data": {"text": str(text)}}


def is_local_reference(reference: str) -> bool:
    """判断引用是否是 Flandora 能直接使用的本机路径 / ``file://``。"""

    text = str(reference or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(HTTP_PREFIXES) or lowered.startswith(BASE64_URI_PREFIX):
        return False
    return True


def _inline_reference(component: Mapping[str, Any]) -> str:
    """取组件内联字节对应的 ``base64://`` 引用。"""

    inline = str(component.get("binary_data_base64") or "").strip()
    return f"{BASE64_URI_PREFIX}{inline}" if inline else ""


def _component_reference(component: Mapping[str, Any]) -> str:
    """取组件 ``data`` 里的引用字符串。"""

    data = component.get("data")
    if isinstance(data, str):
        return data.strip()
    return str(_as_mapping(data).get("file") or _as_mapping(data).get("url") or "").strip()


def _image_segment(component: Mapping[str, Any], result: OutboundSegments, logger: Any) -> None:
    """把 image / emoji 组件转成图片段。"""

    inline = _inline_reference(component)
    if inline:
        result.segments.append({"type": "image", "data": {"file": inline}})
        return

    reference = _component_reference(component)
    if not reference:
        result.dropped.append("image:没有可用的图片引用")
        return
    if is_local_reference(reference):
        result.segments.append({"type": "image", "data": {"file": reference}})
        return

    logger.warning(f"出站图片只给了网络地址，Flandora 不代下，已跳过：{reference}")
    result.dropped.append(f"image:网络地址不代下（{reference}）")


def _flatten_forward(component: Mapping[str, Any], logger: Any) -> str:
    """把合并转发组件展开成一段文本。"""

    nodes = component.get("data")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        return "[合并转发]"

    lines: List[str] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        nickname = str(node.get("user_nickname") or node.get("user_id") or "").strip()
        contents = node.get("content")
        parts: List[str] = []
        if isinstance(contents, Sequence) and not isinstance(contents, (str, bytes)):
            for item in contents:
                if not isinstance(item, Mapping):
                    continue
                kind = str(item.get("type") or "").strip().lower()
                if kind == COMPONENT_TEXT:
                    data = item.get("data")
                    text = (
                        data if isinstance(data, str) else str(_as_mapping(data).get("text") or "")
                    )
                    if text:
                        parts.append(text)
                elif kind == COMPONENT_AT:
                    target = str(_as_mapping(item.get("data")).get("target_user_id") or "").strip()
                    parts.append(f"@{target}")
                elif kind == COMPONENT_IMAGE:
                    parts.append(PLACEHOLDER_PICTURE)
                elif kind == COMPONENT_VOICE:
                    parts.append(PLACEHOLDER_VOICE)
                elif kind == COMPONENT_FILE:
                    name = str(_as_mapping(item.get("data")).get("name") or "").strip()
                    parts.append(f"[文件] {name}" if name else "[文件]")
                else:
                    parts.append(f"[{kind or '未知'}]")
        body = "".join(parts).strip() or "[空节点]"
        lines.append(f"{nickname}：{body}" if nickname else body)

    if not lines:
        logger.warning("合并转发组件里没有可展开的节点")
        return "[合并转发]"
    return "[合并转发]\n" + "\n".join(lines)


def build_outbound_segments(
    components: Sequence[Any],
    *,
    logger: Any,
) -> OutboundSegments:
    """把宿主组件列表翻译成 Flandora 能接受的段列表。

    Args:
        components: 宿主 ``raw_message`` 组件列表。
        logger: 插件日志对象。

    Returns:
        OutboundSegments: 段列表与被降级/跳过的段说明。
    """

    result = OutboundSegments()

    for raw_component in components:
        if not isinstance(raw_component, Mapping):
            logger.debug(f"出站组件不是映射，已跳过：{type(raw_component).__name__}")
            continue
        kind = str(raw_component.get("type") or "").strip().lower()

        if kind == COMPONENT_TEXT:
            data = raw_component.get("data")
            text = data if isinstance(data, str) else str(_as_mapping(data).get("text") or "")
            if text:
                result.segments.append(text_segment(text))
            continue

        if kind == COMPONENT_AT:
            target = str(_as_mapping(raw_component.get("data")).get("target_user_id") or "").strip()
            if target.isdigit():
                result.segments.append({"type": "at", "data": {"qq": int(target)}})
            else:
                logger.warning(f"出站 at 段的目标不是数字 ID，已跳过：{target or '<空>'}")
                result.dropped.append(f"at:目标不是数字 ID（{target or '空'}）")
            continue

        if kind == COMPONENT_IMAGE or kind == COMPONENT_EMOJI:
            _image_segment(raw_component, result, logger)
            continue

        if kind == COMPONENT_VOICE:
            inline = _inline_reference(raw_component)
            reference = inline or _component_reference(raw_component)
            if reference and (inline or is_local_reference(reference)):
                result.segments.append({"type": "record", "data": {"file": reference}})
            else:
                logger.warning(f"出站语音没有可用的本地引用，已跳过：{reference or '<空>'}")
                result.dropped.append("voice:没有可用的本地引用")
            continue

        if kind == COMPONENT_FILE:
            info = _as_mapping(raw_component.get("data"))
            name = str(info.get("name") or "").strip()
            label = f"[文件] {name}" if name else "[文件]"

            inline = str(info.get("base64") or "").strip()
            url = str(info.get("url") or "").strip()
            if inline:
                segment_data: Dict[str, Any] = {"file": f"{BASE64_URI_PREFIX}{inline}"}
                if name:
                    segment_data["name"] = name
                result.segments.append({"type": "file", "data": segment_data})
            elif url and is_local_reference(url):
                segment_data = {"file": url}
                if name:
                    segment_data["name"] = name
                result.segments.append({"type": "file", "data": segment_data})
            else:
                logger.warning(f"出站文件没有可用的本地引用，已降级为文本：{url or '<空>'}")
                result.dropped.append(f"file:降级为文本（{url or '无引用'}）")
                result.segments.append(text_segment(label))
            continue

        if kind == COMPONENT_REPLY:
            # 引用关系由 Flandora 的发送侧维护：这里跳过 reply 段只发正文，限制见 docs/wip.md
            logger.debug("出站 reply 段跳过（引用关系由 Flandora 的发送侧维护）")
            result.dropped.append("reply:引用段跳过")
            continue

        if kind == COMPONENT_FORWARD:
            result.segments.append(text_segment(_flatten_forward(raw_component, logger)))
            result.dropped.append("forward:展开为文本")
            continue

        logger.warning(f"未识别的出站组件类型，已跳过：{kind or '<空>'}")
        result.dropped.append(f"{kind or '未知'}:未识别的类型")

    return result
