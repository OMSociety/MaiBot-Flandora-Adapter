"""连接层的行为测试。

覆盖一个真实踩过的坑：上线钩子里会调动作（取机器人账号、读状态、上报宿主），
而动作的响应只能由读循环收——钩子若被同步 await，读循环就起不来，动作只能一路超时。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import load

transport_mod = load("transport")


class StubSettings:
    """连接层只用到这几个字段，用一个轻量对象顶替真实配置模型。"""

    action_timeout_sec = 0.6
    reconnect_delay_sec = 0.05
    max_reconnect_delay_sec = 0.1
    heartbeat_interval_sec = 30.0
    server = "127.0.0.1"
    port = 7999
    token = ""

    def __init__(self, uri: str = "ws://127.0.0.1:7999/") -> None:
        self._uri = uri
        self.closed = False

    def build_ws_uri(self) -> str:
        return self._uri


class FakeWebSocket:
    """收到动作请求就立刻回一个 ok 响应；close() 结束读取迭代。"""

    def __init__(self) -> None:
        self._inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.close_reason = ""

    async def send(self, raw: str) -> None:
        request = json.loads(raw)
        self.sent.append(request)
        await self._inbox.put(
            json.dumps(
                {"status": "ok", "retcode": 0, "data": {"user_id": 4242}, "echo": request["echo"]},
                ensure_ascii=False,
            )
        )

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        item = await self._inbox.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_reason = reason
        await self._inbox.put(None)

    async def push(self, raw: str) -> None:
        """从服务端方向塞一条报文（事件用）。"""

        await self._inbox.put(raw)


class FakeConnect:
    def __init__(self, ws: FakeWebSocket) -> None:
        self._ws = ws

    async def __aenter__(self) -> FakeWebSocket:
        return self._ws

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest.fixture
def patched_connect(monkeypatch):
    def _install(ws: FakeWebSocket) -> None:
        monkeypatch.setattr(transport_mod.websockets, "connect", lambda *a, **kw: FakeConnect(ws))

    return _install


def test_connected_hook_can_call_actions(logger, patched_connect):
    """上线钩子里的动作必须能拿到响应，而不是等读循环等到超时。"""

    async def scenario() -> None:
        ws = FakeWebSocket()
        patched_connect(ws)

        hook_done = asyncio.Event()
        results: list[dict] = []
        transport = None

        async def on_connected() -> None:
            assert transport is not None
            results.append(await transport.call_action("get_login_info"))
            hook_done.set()

        async def on_event(payload: dict) -> None:  # pragma: no cover - 本用例不发事件
            return

        transport = transport_mod.FlandoraTransport(
            settings=StubSettings(),
            logger=logger,
            on_event=on_event,
            on_connected=on_connected,
        )
        transport.start()

        await asyncio.wait_for(hook_done.wait(), timeout=5.0)
        assert results == [
            {"status": "ok", "retcode": 0, "data": {"user_id": 4242}, "echo": "get_login_info#1"}
        ]

        await transport.stop()
        assert not transport.connected

    asyncio.run(scenario())


def test_connected_hook_failure_keeps_connection(logger, patched_connect):
    """钩子抛异常只记日志，连接本身应当继续可用。"""

    async def scenario() -> None:
        ws = FakeWebSocket()
        patched_connect(ws)

        hook_done = asyncio.Event()

        async def on_connected() -> None:
            hook_done.set()
            raise RuntimeError("钩子里出错")

        async def on_event(payload: dict) -> None:  # pragma: no cover
            return

        transport = transport_mod.FlandoraTransport(
            settings=StubSettings(),
            logger=logger,
            on_event=on_event,
            on_connected=on_connected,
        )
        transport.start()

        await asyncio.wait_for(hook_done.wait(), timeout=5.0)
        await asyncio.sleep(0.1)

        assert transport.connected is True

        await transport.stop()

    asyncio.run(scenario())


def test_event_handler_can_call_actions(logger, patched_connect):
    """处理事件时调动作也必须拿到响应——通知里现查昵称走的就是这条路径。"""

    async def scenario() -> None:
        ws = FakeWebSocket()
        patched_connect(ws)

        handled = asyncio.Event()
        results: list[dict] = []
        transport = None

        async def on_event(payload: dict) -> None:
            assert payload["post_type"] == "notice"
            assert transport is not None
            results.append(await transport.call_action("get_stranger_info", {"user_id": 7}))
            handled.set()

        transport = transport_mod.FlandoraTransport(
            settings=StubSettings(),
            logger=logger,
            on_event=on_event,
        )
        transport.start()
        await asyncio.sleep(0.05)
        await ws.push(json.dumps({"post_type": "notice", "notice_type": "notify"}))

        await asyncio.wait_for(handled.wait(), timeout=5.0)
        assert results and results[0]["status"] == "ok"

        await transport.stop()

    asyncio.run(scenario())


def test_wrong_token_surfaces_as_action_error(logger, monkeypatch):
    """服务端拒绝握手时应抛出可读的连接错误，而不是静默重试。"""

    async def scenario() -> None:
        attempts: list[str] = []

        def _failing_connect(uri, **kwargs):
            attempts.append(uri)
            raise OSError("server rejected WebSocket connection: HTTP 401")

        monkeypatch.setattr(transport_mod.websockets, "connect", _failing_connect)

        async def on_event(payload: dict) -> None:  # pragma: no cover
            return

        transport = transport_mod.FlandoraTransport(
            settings=StubSettings("ws://127.0.0.1:7999/?access_token=bad"),
            logger=logger,
            on_event=on_event,
        )
        transport.start()
        await asyncio.sleep(0.3)

        with pytest.raises(transport_mod.FlandoraActionError):
            await transport.call_action("get_login_info", timeout=0.5)

        await transport.stop()
        assert attempts and attempts[0].endswith("access_token=bad")

    asyncio.run(scenario())
