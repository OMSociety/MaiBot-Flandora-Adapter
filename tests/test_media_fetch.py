"""跨机入站媒体取件与载荷折叠的测试。

覆盖三件事：Flandora 只给 http 地址时把媒体取到本机、同机路径不重复下载、
以及内联 base64 不会以文本形态进入日志或兜底文本。
"""

from __future__ import annotations

import asyncio
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import NullLogger, load

media = load("services.media_fetch")
redact = load("redact")
inbound = load("codecs.inbound")
debug_mod = load("debug")

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
_WAV = b"RIFF" + b"\x00" * 128


class _Handler(BaseHTTPRequestHandler):
    """按路径返回图片、音频与 404。"""

    def log_message(self, *args) -> None:  # noqa: ANN002 - 基类签名
        pass

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - 基类约定
        path = self.path.split("?", 1)[0]
        if path == "/pic.jpg":
            self._send(200, _PNG)
        elif path == "/voice.wav":
            self._send(200, _WAV)
        else:
            self._send(404, b"")


@pytest.fixture
def http_base():
    """起一个本地 HTTP 服务，返回它的根地址。"""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _prefetch(segments, **kwargs):
    return asyncio.run(
        media.prefetch_inbound(segments, logger=NullLogger(), max_bytes=1024 * 1024, **kwargs)
    )


def test_http_image_is_fetched_and_points_at_local_copy(http_base):
    """只有 http 地址的图片段应落成本机文件，临时副本用完即删。"""

    segments = [
        {
            "type": "image",
            "data": {"url": f"{http_base}/pic.jpg", "file": "file:///nonexistent/abc.jpg"},
        }
    ]

    rewritten, staged = _prefetch(segments)

    assert len(staged) == 1
    assert Path(rewritten[0]["data"]["file"]) == staged[0]
    assert staged[0].read_bytes() == _PNG
    for path in staged:
        media.release(path)
    assert not staged[0].exists()


def test_local_file_is_not_downloaded_again(http_base):
    """同机部署下 ``file`` 已经读得到，不该再发一次网络请求。"""

    local = Path(tempfile.mkdtemp(prefix="flandora-inbound-test-")) / "here.jpg"
    local.write_bytes(_PNG)
    segments = [{"type": "image", "data": {"file": str(local), "url": f"{http_base}/pic.jpg"}}]

    rewritten, staged = _prefetch(segments)

    assert staged == []
    assert rewritten[0] == segments[0]


def test_failed_download_keeps_segment_for_placeholder(http_base):
    """取件失败的段原样返回，由编解码层降级为占位文本。"""

    segments = [{"type": "image", "data": {"url": f"{http_base}/nope.jpg"}}]

    rewritten, staged = _prefetch(segments)

    assert staged == []
    assert rewritten[0] == segments[0]


def test_segment_without_url_is_left_alone():
    """没有地址的段（同机路径、file_id）不触发网络请求。"""

    segments = [{"type": "record", "data": {"file": "D:/media/a.wav"}}]

    rewritten, staged = _prefetch(segments)

    assert staged == []
    assert rewritten[0] == segments[0]


def test_voice_over_limit_is_skipped(http_base):
    """超过单件上限的媒体不落盘。"""

    segments = [{"type": "record", "data": {"url": f"{http_base}/voice.wav"}}]

    rewritten, staged = asyncio.run(
        media.prefetch_inbound(segments, logger=NullLogger(), max_bytes=64)
    )

    assert staged == []
    assert rewritten[0] == segments[0]


def test_fold_inline_base64_collapses_long_payloads():
    """长 base64 折叠成字数说明，短串原样保留。"""

    long_payload = "A" * 200
    assert redact.fold_inline_base64(f"[CQ:image,file=base64://{long_payload}]") == (
        "[CQ:image,file=base64://<200 字符已省略>]"
    )
    assert redact.fold_inline_base64("base64://abc") == "base64://abc"
    assert redact.fold_inline_base64("普通文本") == "普通文本"


def test_raw_message_fallback_never_carries_binary():
    """段缺失时回落 ``raw_message``，内联载荷必须已折叠。"""

    payload = {
        "message_id": "1",
        "message_type": "group",
        "group_id": "9",
        "user_id": "7",
        "message": None,
        "raw_message": "[CQ:image,file=base64://" + "B" * 4096 + "]",
    }

    built = inbound.build_inbound_segments(
        payload, self_id="7", attachment_max_bytes=1024 * 1024, logger=NullLogger()
    )

    text = built.components[0]["data"]
    assert "B" * 100 not in text
    assert "已省略" in text


def test_debug_log_never_carries_binary():
    """原始事件日志要折叠内联载荷。"""

    seen: list[str] = []

    class _Logger:
        def info(self, message: str, *args, **kwargs) -> None:  # noqa: ANN002
            seen.append(message)

    logger = debug_mod.FlandoraDebugLogger(_Logger(), enabled=True)
    logger.raw_event({"message": [{"type": "image", "data": {"file": "base64://" + "C" * 4096}}]})

    assert seen and "C" * 100 not in seen[0]
    assert "已省略" in seen[0]
