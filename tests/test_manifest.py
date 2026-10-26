"""清单文件与仓库自带资源的结构校验。

只校验结构与约定（宿主侧的字段规则见 ``src/plugin_runtime/runner/manifest_validator.py``），
不依赖宿主的运行环境，因此可以脱离麦麦单独跑。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REQUIRED_FIELDS = (
    "manifest_version",
    "id",
    "version",
    "name",
    "description",
    "author",
    "license",
    "urls",
    "host_application",
    "sdk",
    "capabilities",
    "i18n",
)

PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)+$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ICON_SUFFIXES = {".jpg", ".jpeg", ".png", ".svg", ".webp"}


@pytest.fixture
def manifest(repo_root: Path) -> dict:
    """读取并解析 ``_manifest.json``。"""

    with (repo_root / "_manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def test_manifest_has_all_required_fields(manifest: dict):
    missing = [field for field in REQUIRED_FIELDS if field not in manifest]

    assert missing == []


def test_manifest_version_is_two(manifest: dict):
    assert manifest["manifest_version"] == 2


def test_plugin_id_matches_host_pattern(manifest: dict):
    assert PLUGIN_ID_PATTERN.match(manifest["id"])
    assert manifest["id"] == "omsociety.flandora-adapter"


def test_version_is_strict_three_part(manifest: dict):
    assert VERSION_PATTERN.match(manifest["version"])


def test_declares_adapter_type_and_license(manifest: dict):
    assert manifest.get("plugin_type") == "adapter"
    assert manifest["license"] == "AGPL-v3.0-or-later"


def test_capabilities_stay_empty(manifest: dict):
    # 网关 RPC 走 call_host_method，不经能力闸；声明了反而只会触发 capability-unused。
    assert manifest["capabilities"] == []


def test_websockets_dependency_declared(manifest: dict):
    dependencies = manifest.get("dependencies") or []
    names = {item.get("name") for item in dependencies if isinstance(item, dict)}

    assert "websockets" in names


def test_icon_file_exists_and_suffix_supported(manifest: dict, repo_root: Path):
    icon = manifest["display"]["icon"]
    assert icon["type"] == "local"
    value = icon["value"]

    assert not Path(value).is_absolute()
    assert ".." not in Path(value).parts
    assert Path(value).suffix.lower() in ICON_SUFFIXES

    icon_path = repo_root / value
    assert icon_path.is_file()
    assert "svg" in icon_path.read_text(encoding="utf-8", errors="ignore")[:200].lower()


def test_host_and_sdk_ranges_are_well_formed(manifest: dict):
    for key in ("host_application", "sdk"):
        section = manifest[key]
        assert VERSION_PATTERN.match(section["min_version"])
        assert VERSION_PATTERN.match(section["max_version"])


def test_urls_point_at_this_repository(manifest: dict):
    repository = manifest["urls"]["repository"]

    assert repository.startswith("https://")
    assert "MaiBot-Flandora-Adapter" in repository


def test_license_file_contains_full_agpl_text(repo_root: Path):
    license_path = repo_root / "LICENSE"
    assert license_path.is_file()

    text = license_path.read_text(encoding="utf-8")
    assert text.startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in text
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text


def test_plugin_entry_declares_gateway(logger, repo_root: Path):
    """入口模块应能构造插件并注册一个双工网关组件。"""

    pytest.importorskip("maibot_sdk", reason="需要麦麦宿主环境")

    from conftest import load

    module = load("plugin")
    instance = module.create_plugin()
    components = instance.get_components()

    types_seen = {component.get("type") for component in components}
    names = {component.get("name") for component in components}

    assert "MESSAGE_GATEWAY" in types_seen
    assert "flandora_gateway" in names
