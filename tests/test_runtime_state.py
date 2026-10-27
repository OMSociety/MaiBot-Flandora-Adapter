"""运行状态上报测试。"""

from __future__ import annotations

import asyncio

from conftest import load

runtime_state = load("runtime_state")


class _Gateway:
    """记录上报调用的网关替身。"""

    def __init__(self, *, accepted: bool = True, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._accepted = accepted
        self._error = error

    async def update_state(self, **kwargs):
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)
        return self._accepted


def _state(logger):
    return runtime_state.FlandoraRuntimeState(
        gateway_name="flandora_gateway",
        platform="wechat",
        logger=logger,
    )


def test_report_connected_sends_account(logger):
    gateway = _Gateway()
    state = _state(logger)

    accepted = asyncio.run(
        state.report_connected(gateway, account_id=" 42 ", scope="flandora", metadata={"a": 1})
    )

    assert accepted is True
    assert state.account_id == "42"
    assert gateway.calls == [
        {
            "gateway_name": "flandora_gateway",
            "ready": True,
            "platform": "wechat",
            "account_id": "42",
            "scope": "flandora",
            "metadata": {"a": 1},
        }
    ]


def test_report_connected_without_account_skips(logger):
    gateway = _Gateway()
    state = _state(logger)

    assert asyncio.run(state.report_connected(gateway, account_id="   ")) is False
    assert gateway.calls == []
    assert state.account_id == ""


def test_report_connected_reports_rejection(logger):
    gateway = _Gateway(accepted=False)
    state = _state(logger)

    assert asyncio.run(state.report_connected(gateway, account_id="42")) is False
    assert len(gateway.calls) == 1


def test_report_connected_reports_failure(logger):
    gateway = _Gateway(error=RuntimeError("宿主不在线"))
    state = _state(logger)

    assert asyncio.run(state.report_connected(gateway, account_id="42")) is False


def test_report_disconnected_after_connected(logger):
    gateway = _Gateway()
    state = _state(logger)
    asyncio.run(state.report_connected(gateway, account_id="42", scope="flandora"))

    accepted = asyncio.run(state.report_disconnected(gateway, reason="链路断开"))

    assert accepted is True
    assert gateway.calls[-1]["ready"] is False
    assert gateway.calls[-1]["account_id"] == "42"
    assert gateway.calls[-1]["scope"] == "flandora"


def test_report_disconnected_without_state_is_noop(logger):
    gateway = _Gateway()
    state = _state(logger)

    assert asyncio.run(state.report_disconnected(gateway)) is False
    assert gateway.calls == []
