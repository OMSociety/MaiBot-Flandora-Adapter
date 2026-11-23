"""入站媒体的取件：把 Flandora 给的 http 地址落成本机临时文件。

Flandora 与适配器不在同一台机器上时，语音、视频、图片与文件都只带 http ``url``
（本机路径在同机部署下另有 ``file`` 字段，那条路直接读盘，不走这里）。这里只做
「按地址取一份临时副本」，段结构的改写由 :mod:`codecs.segments_in` 完成。

取件失败一律降级为占位文本：宁可让模型看见「[图片]」三个字，也不要因为一张图下载
失败而丢整条消息。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

from ..constants import (
    FILE_URI_PREFIX,
    MEDIA_FETCH_TIMEOUT_SEC,
    SEGMENT_EMOJI,
    SEGMENT_FILE,
    SEGMENT_IMAGE,
    SEGMENT_RECORD,
    SEGMENT_VIDEO,
)
from .file_transfer import (
    OutboundFileError,
    StagedFile,
    download_media,
    remove_staged,
)

_TEMP_PREFIX = "flandora-inbound-"

# 需要取件的段类型 → 落盘时优先用的扩展名（地址里取不到像样的名字时兜底）
_FALLBACK_SUFFIX = {
    SEGMENT_IMAGE: ".jpg",
    SEGMENT_EMOJI: ".gif",
    SEGMENT_RECORD: ".wav",
    SEGMENT_VIDEO: ".mp4",
    SEGMENT_FILE: "",
}

MEDIA_SEGMENTS = frozenset(_FALLBACK_SUFFIX)


def media_url(data: Any) -> str:
    """取段里可下载的 http 地址；没有则返回空串。

    只看 ``url``：``file`` 是同机部署下的本机路径，``file_id`` 要客户端再发一次动作
    换取地址，两条路都不该在这一层触发网络请求。
    """

    if not isinstance(data, dict):
        return ""
    raw = str(data.get("url") or "").strip()
    lowered = raw.lower()
    return raw if lowered.startswith(("http://", "https://")) else ""


def reference_name(data: Any, kind: str) -> str:
    """给取到的临时文件取名：段里声明的名字优先，其次是地址里的文件名。"""

    if isinstance(data, dict):
        name = str(data.get("name") or data.get("file_name") or "").strip()
        if name:
            return name
    url = media_url(data)
    if url:
        base = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).strip()
        if base:
            return base
    return f"media{_FALLBACK_SUFFIX.get(kind, '')}"


async def fetch_segment_media(
    kind: str,
    data: Any,
    *,
    max_bytes: int,
    timeout: float = MEDIA_FETCH_TIMEOUT_SEC,
) -> Optional[Path]:
    """按段里的 http 地址取一份临时文件。

    Args:
        kind: 段类型（``image`` / ``record`` / ``video`` / ``file`` / ``emoji``）。
        data: 段里的 ``data`` 字段。
        max_bytes: 单件上限。
        timeout: 单件超时（秒）。

    Returns:
        Optional[Path]: 落到本机的临时文件；没有地址、超限或取件失败时返回 ``None``。
    """

    url = media_url(data)
    if not url:
        return None
    try:
        staged: StagedFile = await download_media(
            url,
            filename=reference_name(data, kind),
            max_bytes=max_bytes,
            timeout=timeout,
            prefix=_TEMP_PREFIX,
        )
    except (OutboundFileError, TimeoutError, OSError, ValueError):
        return None
    return staged.path


def release(path: Optional[Path]) -> None:
    """删掉取件留下的临时文件与它的目录。"""

    if path is None:
        return
    remove_staged([StagedFile(path=path, directory=path.parent)])


def _local_file_exists(data: Mapping[str, Any]) -> bool:
    """段里的 ``file`` 在本机读得到时返回真：同机部署直接读盘，不必再下载。"""

    reference = str(data.get("file") or "").strip()
    if not reference or reference.lower().startswith(("http://", "https://", "base64://")):
        return False
    if reference.startswith(FILE_URI_PREFIX):
        parsed = urlsplit(reference)
        raw_path = unquote(parsed.path or "")
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{raw_path}"
        if len(raw_path) > 2 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        reference = raw_path
    try:
        return Path(reference).is_file()
    except OSError:
        return False


async def prefetch_inbound(
    segments: Sequence[Any],
    *,
    max_bytes: int,
    logger: Any,
    timeout: float = MEDIA_FETCH_TIMEOUT_SEC,
) -> Tuple[List[Any], List[Path]]:
    """把本机读不到、但带 http 地址的媒体段取到本机，``file`` 改指向临时副本。

    同机部署（``file`` 在本机存在）与没有地址的段原样返回。取件失败的段也原样返回，
    由编解码层按「读不到」降级为占位文本。返回的临时文件在消息编码完成后由调用方
    :func:`release` 掉；编码层已把内容读进内存，不会再用到它们。

    Args:
        segments: Flandora 事件里的 ``message`` 段数组。
        max_bytes: 单件上限（字节），与 ``attachment_max_mb`` 一致。
        logger: 插件日志对象。
        timeout: 单件下载超时（秒）。

    Returns:
        Tuple[List[Any], List[Path]]: 改写后的段列表（浅拷贝，不改原事件）与临时文件列表。
    """

    rewritten: List[Any] = []
    staged: List[Path] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            rewritten.append(segment)
            continue
        kind = str(segment.get("type") or "").strip().lower()
        data = segment.get("data")
        if kind not in MEDIA_SEGMENTS or not isinstance(data, Mapping):
            rewritten.append(segment)
            continue
        if _local_file_exists(data) or not media_url(data):
            rewritten.append(segment)
            continue
        path = await fetch_segment_media(kind, data, max_bytes=max_bytes, timeout=timeout)
        if path is None:
            logger.warning(f"{kind} 段的地址取不到，将按占位文本处理")
            rewritten.append(segment)
            continue
        staged.append(path)
        updated = dict(data)
        updated["file"] = str(path)
        rewritten.append({**segment, "data": updated})
    return rewritten, staged
