"""Flandora OneBot v11 正向 WebSocket 连接层。

承担三件事：维持与 Flandora 的长连接（自动重连 + 空闲看护）、
按 ``echo`` 匹配动作请求的响应、把事件交回上层分派。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

import websockets

if TYPE_CHECKING:  # 只用于注记：连接层只用到配置对象上的几个字段，不依赖宿主 SDK
    from .config import FlandoraClientConfig

EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]
ConnectedHook = Callable[[], Awaitable[None]]
DisconnectedHook = Callable[[str], Awaitable[None]]

# 连接存活时间低于该秒数时视为“连上即掉”，退避间隔不重置。
_STABLE_CONNECTION_SEC = 5.0
_CLOSE_TIMEOUT_SEC = 5.0


class FlandoraActionError(RuntimeError):
    """一次动作请求失败。"""

    def __init__(self, action: str, message: str, retcode: int = -1) -> None:
        """初始化异常。

        Args:
            action: 动作名。
            message: 失败原因。
            retcode: Flandora 返回的 retcode；未拿到响应时为 -1。
        """

        super().__init__(message)
        self.action = action
        self.message = message
        self.retcode = retcode


class FlandoraTransport:
    """与 Flandora 之间的 WebSocket 长连接。"""

    def __init__(
        self,
        *,
        settings: "FlandoraClientConfig",
        logger: Any,
        on_event: EventHandler,
        on_connected: Optional[ConnectedHook] = None,
        on_disconnected: Optional[DisconnectedHook] = None,
    ) -> None:
        """初始化连接层。

        Args:
            settings: 连接配置。
            logger: 插件日志对象。
            on_event: 收到非动作响应事件时的回调。
            on_connected: 连接建立后的回调。
            on_disconnected: 连接断开后的回调，参数为断开原因。
        """

        self._settings = settings
        self._logger = logger
        self._on_event = on_event
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        self._ws: Any = None
        self._runner_task: Optional[asyncio.Task[None]] = None
        self._event_task: Optional[asyncio.Task[None]] = None
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._pending: Dict[str, asyncio.Future[Dict[str, Any]]] = {}
        self._echo_seq = 0
        self._last_event_at = 0.0
        self._closed = False
        self._connected = False

    @property
    def connected(self) -> bool:
        """当前是否已建立连接。"""

        return self._connected and self._ws is not None

    def start(self) -> None:
        """启动后台连接任务。"""

        if self._runner_task is not None and not self._runner_task.done():
            return
        self._closed = False
        self._runner_task = asyncio.create_task(self._run_forever(), name="flandora-transport")
        self._event_task = asyncio.create_task(self._drain_events(), name="flandora-events")

    async def stop(self) -> None:
        """关闭连接并等待后台任务结束。"""

        self._closed = True
        task = self._runner_task
        self._runner_task = None
        event_task = self._event_task
        self._event_task = None

        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close(code=1000, reason="plugin unload")

        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if event_task is not None and not event_task.done():
            event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await event_task

        self._fail_pending("连接已关闭")

    def update_settings(self, settings: "FlandoraClientConfig") -> None:
        """就地替换连接参数，供配置热更新使用（调用方负责判断是否需要重建连接）。"""

        self._settings = settings

    async def call_action(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送一次动作请求并等待响应。

        Args:
            action: 动作名。
            params: 动作参数。
            timeout: 超时秒数；留空时取配置里的动作超时。

        Returns:
            Dict[str, Any]: Flandora 返回的原始响应字典。

        Raises:
            FlandoraActionError: 未连接、发送失败或等待超时。
        """

        ws = self._ws
        if ws is None:
            raise FlandoraActionError(action, "尚未连接 Flandora，请检查服务端地址与端口")

        self._echo_seq += 1
        echo = f"{action}#{self._echo_seq}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending[echo] = future

        effective_timeout = (
            timeout if timeout and timeout > 0 else self._settings.action_timeout_sec
        )
        payload = {"action": action, "params": params or {}, "echo": echo}

        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            self._pending.pop(echo, None)
            raise FlandoraActionError(action, f"发送动作 {action} 失败：{exc}") from exc

        try:
            return await asyncio.wait_for(future, effective_timeout)
        except asyncio.TimeoutError as exc:
            raise FlandoraActionError(
                action, f"动作 {action} 等待响应超时（{effective_timeout:.1f} 秒）"
            ) from exc
        finally:
            self._pending.pop(echo, None)

    async def _run_forever(self) -> None:
        """后台连接循环：连接、断线、按指数退避重连。"""

        delay = self._settings.reconnect_delay_sec
        max_delay = max(self._settings.max_reconnect_delay_sec, delay)

        while not self._closed:
            started_at = time.monotonic()
            try:
                await self._connect_once()
                if time.monotonic() - started_at >= _STABLE_CONNECTION_SEC:
                    delay = self._settings.reconnect_delay_sec
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.warning(f"连接 Flandora 失败：{exc}；{delay:.1f} 秒后重试")

            if self._closed:
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _connect_once(self) -> None:
        """建立一次连接并读取消息，直到连接结束。"""

        uri = self._settings.build_ws_uri()
        token_note = "带访问令牌" if self._settings.token else "无访问令牌"
        self._logger.info(
            f"正在连接 Flandora：ws://{self._settings.server}:{self._settings.port}/（{token_note}）"
        )

        async with websockets.connect(
            uri,
            open_timeout=self._settings.action_timeout_sec,
            close_timeout=_CLOSE_TIMEOUT_SEC,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._last_event_at = time.monotonic()
            watchdog = asyncio.create_task(self._watchdog(ws), name="flandora-watchdog")
            # 上线钩子要调动作（取机器人账号、读状态、上报宿主），而动作的响应只能由下面的
            # 读循环收。所以钩子必须另行起任务，不能在这里 await：await 会把读循环压在钩子
            # 后面，钩子里的动作永远等不到响应，只能一路超时。
            connected_hook = asyncio.create_task(
                self._run_connected_hook(), name="flandora-on-connected"
            )
            try:
                self._logger.info("已连接 Flandora")
                async for raw in ws:
                    self._last_event_at = time.monotonic()
                    await self._handle_raw(raw)
            finally:
                watchdog.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await watchdog
                if not connected_hook.done():
                    connected_hook.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await connected_hook
                self._ws = None
                self._connected = False
                self._fail_pending("连接已断开")
                if self._on_disconnected is not None:
                    with contextlib.suppress(Exception):
                        await self._on_disconnected("连接已断开")

    async def _run_connected_hook(self) -> None:
        """执行上线钩子；钩子失败只记日志，不拆连接。"""

        if self._on_connected is None:
            return
        try:
            await self._on_connected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 钩子失败不应中断链路
            self._logger.warning(f"连接建立后的初始化回调失败：{exc}")

    async def _watchdog(self, ws: Any) -> None:
        """空闲看护：超过心跳阈值仍未收到任何事件时主动断开触发重连。"""

        idle_limit = self._settings.heartbeat_interval_sec * 2 + _STABLE_CONNECTION_SEC
        interval = max(self._settings.heartbeat_interval_sec / 2, 1.0)

        while True:
            await asyncio.sleep(interval)
            if self._closed:
                return
            idle_for = time.monotonic() - self._last_event_at
            if idle_for <= idle_limit:
                continue
            self._logger.warning(
                f"已 {idle_for:.0f} 秒未收到 Flandora 的任何事件，判定链路异常并重建连接"
            )
            await self._close_quietly(ws, "heartbeat timeout")
            return

    async def _close_quietly(self, ws: Any, reason: str) -> None:
        """安静地关闭连接，异常只记调试日志。"""

        with contextlib.suppress(Exception):
            await ws.close(code=1000, reason=reason)

    async def _handle_raw(self, raw: Any) -> None:
        """解析一条报文：动作响应回填 future，其余交给事件回调。"""

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            self._logger.warning("收到解析失败的报文，已忽略")
            return

        if not isinstance(payload, dict):
            self._logger.warning("收到非对象报文，已忽略")
            return

        if "echo" in payload:
            echo = payload.get("echo")
            pending = self._pending.pop(echo, None) if echo is not None else None
            if pending is not None and not pending.done():
                pending.set_result(payload)
            else:
                self._logger.debug("收到迟到的动作响应，已丢弃")
            return

        # 事件进队列、由独立任务按序消费：处理一条事件时可能还要调动作（通知里现查昵称
        # 就是），而动作的响应只能由本循环收。在这里直接 await 回调会把读循环压在回调
        # 后面，回调里的动作永远等不到响应。
        self._event_queue.put_nowait(payload)

    async def _drain_events(self) -> None:
        """按序消费事件队列，把处理与读循环解耦。"""

        while True:
            payload = await self._event_queue.get()
            try:
                await self._on_event(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单条事件失败不应中断队列
                self._logger.error(f"处理入站事件失败：{exc}")
            finally:
                self._event_queue.task_done()

    def _fail_pending(self, reason: str) -> None:
        """让所有等待中的动作请求立即失败。"""

        if not self._pending:
            return
        pending = list(self._pending.items())
        self._pending.clear()
        for echo, future in pending:
            if not future.done():
                action = echo.split("#", 1)[0]
                future.set_exception(FlandoraActionError(action, reason))
