"""调试日志器测试。"""

from __future__ import annotations

from conftest import load

debug_mod = load("debug")


class _Recorder:
    """记录 info 输出的日志替身。"""

    def __init__(self) -> None:
        self.infos: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)


def test_disabled_logger_stays_silent():
    recorder = _Recorder()

    debug_mod.FlandoraDebugLogger(recorder).raw_event({"a": 1})

    assert recorder.infos == []


def test_enabled_logger_writes_payload():
    recorder = _Recorder()

    debug_mod.FlandoraDebugLogger(recorder, enabled=True).raw_event({"text": "你好"})

    assert recorder.infos == ['[Flandora] 原始事件 {"text": "你好"}']


def test_long_payload_is_truncated():
    recorder = _Recorder()

    debug_mod.FlandoraDebugLogger(recorder, enabled=True).raw_event({"text": "x" * 5000})

    message = recorder.infos[0]
    assert "已截断" in message
    assert len(message) < 2100


def test_non_serializable_payload_falls_back_to_repr():
    recorder = _Recorder()

    debug_mod.FlandoraDebugLogger(recorder, enabled=True).raw_event({"bad": {1, 2}})

    assert "Flandora" in recorder.infos[0]


def test_set_enabled_toggles():
    recorder = _Recorder()
    logger = debug_mod.FlandoraDebugLogger(recorder)
    logger.set_enabled(True)

    logger.raw_event({"a": 1})

    assert len(recorder.infos) == 1
