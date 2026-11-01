"""出站文件的暂存：把宿主给的 http 签名地址落成本地文件。

宿主 1.3.16 起，消息网关收到的 ``file`` 段会带一个短时有效的 http 下载地址；
Flandora 只接受本机路径、``file://`` 与 ``base64://``，所以适配器必须先下载。
这里只做「下载 + 校验 + 清理」，不碰消息段结构；段结构的改写由调用方完成。
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..constants import (
    OUTBOUND_FILE_CHUNK_BYTES,
    OUTBOUND_FILE_MAX_BYTES,
    OUTBOUND_FILE_TIMEOUT_SEC,
)

_TEMP_PREFIX = "flandora-outbound-"
_MAX_FILENAME_LENGTH = 120
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


class OutboundFileError(RuntimeError):
    """出站文件无法下载或不满足约束。"""


@dataclass(frozen=True)
class StagedFile:
    """一个已经落到本机临时目录、等待发送的出站文件。"""

    path: Path
    directory: Path


@dataclass
class StagedFiles:
    """一次出站消息的文件暂存结果。"""

    files: list[StagedFile] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝重定向：签名地址本应直接返回文件，重定向只可能把 token 带去别处。"""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        raise OutboundFileError(f"下载地址返回重定向（HTTP {code}），已拒绝")


def remove_staged(files: list[StagedFile] | tuple[StagedFile, ...]) -> None:
    """删除暂存文件与其临时目录；失败只忽略，不向调用方抛错。"""

    for staged in files:
        with contextlib.suppress(OSError):
            staged.path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            staged.directory.rmdir()


async def stage_outbound_files(
    message: dict[str, Any],
    *,
    logger: Any,
    max_bytes: int = OUTBOUND_FILE_MAX_BYTES,
    timeout: float = OUTBOUND_FILE_TIMEOUT_SEC,
) -> StagedFiles:
    """下载消息里所有带 http 地址的 ``file`` 段，并把段里的地址换成本地路径。

    内联 base64、已经是本机路径的段保持原样，交给现有的段编解码处理。下载失败的段会从
    ``raw_message`` 里移除，原因写进 ``StagedFiles.failures``，由调用方并入发送回执。

    Args:
        message: 宿主下发的消息字典；函数会就地替换 ``raw_message``。
        logger: 插件日志对象。
        max_bytes: 单个文件的字节上限。
        timeout: 单个文件的下载超时（秒）。

    Returns:
        StagedFiles: 已暂存的文件与丢弃原因。
    """

    components = message.get("raw_message")
    if not isinstance(components, list):
        return StagedFiles()

    staged = StagedFiles()
    kept: list[Any] = []

    for component in components:
        if not _is_http_file(component):
            kept.append(component)
            continue

        data = component.get("data")
        if not isinstance(data, Mapping):
            kept.append(component)
            continue
        name = str(data.get("name") or "").strip()
        label = name or "文件"
        declared = _declared_size(data.get("size"))

        if declared is not None and declared > max_bytes:
            staged.failures.append(f"file:{label} 超过 {_mib(max_bytes)} MiB 上限")
            logger.warning(f"出站文件超过上限，已丢弃：{label}（{_mib(declared)} MiB）")
            continue

        try:
            file = await _download(
                str(data.get("url") or "").strip(),
                filename=_safe_filename(name),
                max_bytes=max_bytes,
                timeout=timeout,
            )
        except OutboundFileError as exc:
            staged.failures.append(f"file:{label} 下载失败（{exc}）")
            logger.warning(f"出站文件下载失败，已丢弃：{label}（{exc}）")
            continue
        except TimeoutError:
            staged.failures.append(f"file:{label} 下载超时（{timeout:.0f} 秒）")
            logger.warning(f"出站文件下载超时，已丢弃：{label}")
            continue

        staged.files.append(file)
        updated = dict(data)
        updated["url"] = str(file.path)
        kept.append({"type": component.get("type"), "data": updated})

    message["raw_message"] = kept
    return staged


def _is_http_file(component: Any) -> bool:
    """判断组件是否是需要下载的 http ``file`` 段。"""

    if not isinstance(component, Mapping) or str(component.get("type") or "").lower() != "file":
        return False
    data = component.get("data")
    if not isinstance(data, Mapping):
        return False
    if str(data.get("base64") or "").strip():
        return False
    url = str(data.get("url") or "").strip().lower()
    return url.startswith("http://") or url.startswith("https://")


async def _download(url: str, *, filename: str, max_bytes: int, timeout: float) -> StagedFile:
    """在线程里下载，并把整体耗时限制在 ``timeout`` 内。

    暂存目录用普通 ``mkdir`` 创建（系统临时目录下按 uuid 取名），不用
    ``tempfile.mkdtemp``：后者会生成仅创建者令牌可访问的 DACL，插件进程与
    Flandora 的访问令牌不同，Flandora 读不到文件，会报「文件不存在」。
    """

    stage_root = Path(tempfile.gettempdir())
    directory = stage_root / f"{_TEMP_PREFIX}{uuid.uuid4().hex[:8]}"
    await asyncio.to_thread(directory.mkdir, parents=False)
    cancel = threading.Event()
    worker = asyncio.ensure_future(
        asyncio.to_thread(
            _download_blocking,
            directory,
            url,
            filename,
            max_bytes=max_bytes,
            timeout=timeout,
            cancel=cancel,
        )
    )
    try:
        path = await asyncio.wait_for(asyncio.shield(worker), timeout=timeout)
    except BaseException:
        # 超时或取消时线程可能还在写：让它停下并退出后，再删临时目录。
        cancel.set()
        with contextlib.suppress(BaseException):
            await asyncio.shield(worker)
        await asyncio.to_thread(shutil.rmtree, directory, True)
        raise
    return StagedFile(path=path, directory=directory)


def _download_blocking(
    directory: Path,
    url: str,
    filename: str,
    *,
    max_bytes: int,
    timeout: float,
    cancel: threading.Event,
) -> Path:
    """同步下载到 ``directory/filename``，失败抛 :class:`OutboundFileError`。"""

    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise OutboundFileError("下载地址不是可用的 http(s) 地址")
    if parsed.username or parsed.password:
        raise OutboundFileError("下载地址带有凭证，已拒绝")

    target = directory / filename
    total = 0
    request = urllib.request.Request(url, method="GET")
    # 签名地址由宿主按本机监听地址签发，直连即可；显式禁用系统代理，
    # 避免带 HTTP_PROXY 的进程把 127.0.0.1 的下载请求交给代理。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirect)

    try:
        with opener.open(request, timeout=timeout) as response:
            if getattr(response, "status", 200) >= 400:
                raise OutboundFileError(f"HTTP {response.status}")
            length = _declared_size(response.headers.get("Content-Length"))
            if length is not None and length > max_bytes:
                raise OutboundFileError(f"文件 {_mib(length)} MiB 超过 {_mib(max_bytes)} MiB 上限")
            with target.open("xb") as handle:
                while not cancel.is_set():
                    chunk = response.read(OUTBOUND_FILE_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise OutboundFileError(f"文件超过 {_mib(max_bytes)} MiB 上限，下载已中止")
                    handle.write(chunk)
            if cancel.is_set():
                raise OutboundFileError("下载已取消")
    except OutboundFileError:
        raise
    except urllib.error.HTTPError as exc:
        raise OutboundFileError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OutboundFileError(f"连接失败：{exc}") from exc

    if total == 0:
        raise OutboundFileError("下载到的文件为空")
    return target


def _declared_size(raw: Any) -> int | None:
    """解析宿主或响应头给出的大小；缺失或非法时返回 ``None``。"""

    if raw is None:
        return None
    try:
        size = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


def _safe_filename(name: str) -> str:
    """把宿主给的文件名收成单层、Windows 可用的文件名，保留扩展名。"""

    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = "".join(
        "_" if character in _INVALID_FILENAME_CHARS or ord(character) < 32 else character
        for character in base
    ).strip(" .")
    if not cleaned:
        return "file"
    if len(cleaned) <= _MAX_FILENAME_LENGTH:
        return cleaned
    suffix = Path(cleaned).suffix
    if len(suffix) >= _MAX_FILENAME_LENGTH:
        return cleaned[:_MAX_FILENAME_LENGTH]
    return cleaned[: _MAX_FILENAME_LENGTH - len(suffix)] + suffix


def _mib(size: int) -> str:
    """把字节数显示成一位小数的 MiB。"""

    return f"{size / (1024 * 1024):.0f}"
