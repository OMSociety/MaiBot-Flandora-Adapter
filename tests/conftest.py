"""测试夹具。

插件根目录名带连字符（``MaiBot-Flandora-Adapter``），不能直接当包名导入，
所以这里手工构造一个包对象挂进 ``sys.modules``，让插件内部的相对导入能解析。
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "flandora_adapter"

if PACKAGE not in sys.modules:
    _package = types.ModuleType(PACKAGE)
    _package.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
    sys.modules[PACKAGE] = _package


def load(module: str) -> Any:
    """按包内路径导入插件模块。"""

    return importlib.import_module(f"{PACKAGE}.{module}")


class NullLogger:
    """把日志吞掉的桩对象。"""

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass


@pytest.fixture
def logger() -> NullLogger:
    """返回一个静默日志对象。"""

    return NullLogger()


@pytest.fixture
def repo_root() -> Path:
    """插件仓库根目录。"""

    return ROOT
