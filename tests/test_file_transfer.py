"""出站文件暂存的测试：真实 HTTP 服务 + 本地临时目录。

覆盖宿主 1.3.16+ 下发的签名地址这一条链路：下载、限额、拒绝重定向、超时与清理。
"""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import NullLogger, load

transfer = load("services.file_transfer")

_PAYLOAD = b"flandora outbound payload\n"


class _Handler(BaseHTTPRequestHandler):
    """按路径返回不同测试场景。"""

    def log_message(self, *args) -> None:  # noqa: ANN002 - 基类签名
        pass

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - 基类约定
        path = self.path.split("?", 1)[0]
        if path == "/report.pdf":
            self._send(200, _PAYLOAD)
        elif path == "/empty":
            self._send(200, b"")
        elif path == "/missing":
            self.send_error(404)
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/report.pdf")
            self.end_headers()
        elif path == "/slow":
            time.sleep(0.5)
            self._send(200, b"slow")
        elif path == "/large-header":
            self.send_response(200)
            self.send_header("Content-Length", str(10 * 1024 * 1024))
            self.end_headers()
        elif path == "/large-body":
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for _ in range(64):
                    self.wfile.write(b"x" * 4096)
            except OSError:
                pass
        else:
            self.send_error(404)


@pytest.fixture()
def http_base() -> str:
    """起一个本地 HTTP 服务，返回基地址。"""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _message(url: str, *, name: str = "报告.pdf", size: int | None = None) -> dict:
    data: dict[str, object] = {"url": url, "name": name}
    if size is not None:
        data["size"] = str(size)
    return {"raw_message": [{"type": "file", "data": data}]}


def _stage(message: dict, **kwargs):
    return asyncio.run(transfer.stage_outbound_files(message, logger=NullLogger(), **kwargs))


def _temp_dirs() -> list[Path]:
    return list(Path(tempfile.gettempdir()).glob("flandora-outbound-*"))


def test_downloads_http_file_and_rewrites_component(http_base: str):
    """成功的下载应保留原文件名，并把段里的 url 换成本地路径。"""

    message = _message(f"{http_base}/report.pdf")

    staged = _stage(message)

    assert staged.failures == []
    assert len(staged.files) == 1
    local = staged.files[0].path
    assert local.read_bytes() == _PAYLOAD
    assert local.name == "报告.pdf"

    component = message["raw_message"][0]
    assert component["data"]["url"] == str(local)
    assert component["data"]["name"] == "报告.pdf"

    transfer.remove_staged(staged.files)
    assert not local.exists()
    assert not staged.files[0].directory.exists()


def test_declared_size_over_limit_is_dropped_before_download(http_base: str):
    """宿主给出的 size 已超限时直接丢弃，不发起下载。"""

    message = _message(f"{http_base}/report.pdf", size=51 * 1024 * 1024)

    staged = _stage(message)

    assert staged.files == []
    assert any("超过 50 MiB 上限" in failure for failure in staged.failures)
    assert message["raw_message"] == []


def test_content_length_over_limit_is_dropped(http_base: str):
    """响应头声明的大小超过上限时，读完头就中止。"""

    message = _message(f"{http_base}/large-header")

    staged = _stage(message, max_bytes=1024)

    assert staged.files == []
    assert any("超过" in failure for failure in staged.failures)


def test_streaming_body_over_limit_is_aborted(http_base: str):
    """没有 Content-Length 时按实际读取量中止。"""

    message = _message(f"{http_base}/large-body")

    staged = _stage(message, max_bytes=1024)

    assert staged.files == []
    assert any("超过" in failure for failure in staged.failures)


def test_http_error_is_reported(http_base: str):
    """404 应回报 HTTP 状态码。"""

    message = _message(f"{http_base}/missing")

    staged = _stage(message)

    assert staged.files == []
    assert any("HTTP 404" in failure for failure in staged.failures)
    assert message["raw_message"] == []


def test_redirect_is_rejected(http_base: str):
    """签名地址不应跳转，重定向一律拒绝。"""

    message = _message(f"{http_base}/redirect")

    staged = _stage(message)

    assert staged.files == []
    assert any("重定向" in failure for failure in staged.failures)


def test_timeout_is_reported_and_temp_dir_cleaned(http_base: str):
    """整体超时后回报原因，线程停下的临时目录也要清掉。"""

    message = _message(f"{http_base}/slow")

    staged = _stage(message, timeout=0.1)

    assert staged.files == []
    assert any("下载超时" in failure for failure in staged.failures)

    time.sleep(0.3)  # 给下载线程留出响应取消信号的时间
    assert _temp_dirs() == []


def test_empty_body_is_reported(http_base: str):
    """空文件视为下载失败，避免给 Flandora 一个空路径。"""

    message = _message(f"{http_base}/empty")

    staged = _stage(message)

    assert staged.files == []
    assert any("为空" in failure for failure in staged.failures)


def test_missing_size_still_downloads(http_base: str):
    """宿主没给 size 时不能预检，下载后按实际字节判断。"""

    message = _message(f"{http_base}/report.pdf", size=None)

    staged = _stage(message)

    assert len(staged.files) == 1
    transfer.remove_staged(staged.files)


def test_inline_and_local_file_segments_are_left_alone():
    """base64 与本机路径不是这条链路的职责，保持原样。"""

    message = {
        "raw_message": [
            {"type": "file", "data": {"name": "a.txt", "base64": "aGk="}},
            {"type": "file", "data": {"name": "b.txt", "url": "D:/tmp/b.txt"}},
        ]
    }

    staged = _stage(message)

    assert staged.files == []
    assert staged.failures == []
    assert message["raw_message"][0]["data"]["base64"] == "aGk="
    assert message["raw_message"][1]["data"]["url"] == "D:/tmp/b.txt"
