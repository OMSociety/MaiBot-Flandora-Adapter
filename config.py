"""Flandora 适配器配置模型。

配置分五节：``[plugin]``、``[client]``、``[filters]``、``[notice]``、``[debug]``。
会话黑白名单不在这里做，交给宿主的适配器策略。
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List
from urllib.parse import quote

from maibot_sdk import Field, PluginConfigBase
from pydantic import ValidationInfo, field_validator

from .constants import (
    BYTES_PER_MB,
    DEFAULT_ACTION_TIMEOUT_SEC,
    DEFAULT_ATTACHMENT_MAX_MB,
    DEFAULT_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_MAX_RECONNECT_DELAY_SEC,
    DEFAULT_RECONNECT_DELAY_SEC,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    SUPPORTED_CONFIG_VERSION,
)

_DELAY_DEFAULTS: Dict[str, float] = {
    "reconnect_delay_sec": DEFAULT_RECONNECT_DELAY_SEC,
    "max_reconnect_delay_sec": DEFAULT_MAX_RECONNECT_DELAY_SEC,
    "heartbeat_interval_sec": DEFAULT_HEARTBEAT_INTERVAL_SEC,
    "action_timeout_sec": DEFAULT_ACTION_TIMEOUT_SEC,
}


def _ui(*, label: str, hint: str, order: int, **extra: Any) -> Dict[str, Any]:
    """构造 WebUI 配置项的展示信息。"""

    payload: Dict[str, Any] = {"label": label, "hint": hint, "order": order}
    payload.update(extra)
    return payload


def _normalize_string(value: Any) -> str:
    """把任意值规整为去空白的字符串。"""

    return "" if value is None else str(value).strip()


def _normalize_positive_float(value: Any, default: float) -> float:
    """规整为正浮点数，非法或非正值时回退默认值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _normalize_positive_int(value: Any, default: int) -> int:
    """规整为正整数，非法或非正值时回退默认值。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _normalize_string_list(value: Any) -> List[str]:
    """规整为去重后的字符串列表。"""

    if isinstance(value, str):
        candidates: List[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        return []

    result: List[str] = []
    for item in candidates:
        normalized = _normalize_string(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _matches_scoped_identifier(allowed_values: List[str], current_value: str) -> bool:
    """兼容 ``platform:id`` 与纯 ID 两种写法。"""

    normalized_current = _normalize_string(current_value)
    if not normalized_current:
        return False
    for allowed_value in allowed_values:
        normalized_allowed = _normalize_string(allowed_value)
        if not normalized_allowed:
            continue
        if normalized_allowed == normalized_current:
            return True
        if normalized_allowed.endswith(f":{normalized_current}"):
            return True
    return False


class FlandoraPluginOptions(PluginConfigBase):
    """插件级开关。"""

    __ui_label__: ClassVar[str] = "插件设置"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=True,
        description="是否启用适配器。",
        json_schema_extra=_ui(
            label="启用适配器",
            hint="关闭后插件保持空闲，不会主动建立 WebSocket 连接。",
            order=0,
        ),
    )
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="当前配置结构版本。",
        json_schema_extra=_ui(
            label="配置版本",
            hint="配置结构版本，由插件维护；与本插件要求的版本不一致时会拒绝启动连接。",
            order=99,
            disabled=True,
            hidden=True,
        ),
    )

    @field_validator("config_version", mode="before")
    @classmethod
    def _normalize_config_version(cls, value: Any) -> str:
        """规范配置版本；留空时回退到当前支持版本。"""

        return _normalize_string(value) or SUPPORTED_CONFIG_VERSION

    def should_connect(self) -> bool:
        """当前配置下是否应当建立连接。"""

        return bool(self.enabled)


class FlandoraClientConfig(PluginConfigBase):
    """Flandora 连接配置。"""

    __ui_label__: ClassVar[str] = "连接"
    __ui_order__: ClassVar[int] = 1

    server: str = Field(
        default=DEFAULT_SERVER_HOST,
        description="Flandora 的 OneBot v11 服务端地址。",
        json_schema_extra=_ui(
            label="服务端地址",
            hint="Flandora 控制面板里 OneBot v11 服务端的监听地址，默认 127.0.0.1。",
            order=0,
        ),
    )
    port: int = Field(
        default=DEFAULT_SERVER_PORT,
        description="Flandora 的 OneBot v11 服务端端口。",
        json_schema_extra=_ui(
            label="服务端端口",
            hint="对应 Flandora 通用设置里的 ob_server_port，默认 7999。",
            order=1,
        ),
    )
    token: str = Field(
        default="",
        description="OneBot v11 服务端的 access_token。",
        json_schema_extra=_ui(
            label="访问令牌",
            hint="对应 Flandora 的 ob_server_token；留空表示不鉴权。以 URL 查询参数形式发送。",
            order=2,
        ),
    )
    reconnect_delay_sec: float = Field(
        default=DEFAULT_RECONNECT_DELAY_SEC,
        description="首次重连等待秒数。",
        json_schema_extra=_ui(
            label="重连初始间隔",
            hint="断线后从这个秒数开始重试，每次失败后翻倍。",
            order=4,
        ),
    )
    max_reconnect_delay_sec: float = Field(
        default=DEFAULT_MAX_RECONNECT_DELAY_SEC,
        description="重连等待秒数的上限。",
        json_schema_extra=_ui(
            label="重连最大间隔",
            hint="指数退避的上限秒数。",
            order=5,
        ),
    )
    heartbeat_interval_sec: float = Field(
        default=DEFAULT_HEARTBEAT_INTERVAL_SEC,
        description="心跳空闲阈值秒数。",
        json_schema_extra=_ui(
            label="心跳空闲阈值",
            hint=(
                "超过该秒数两倍没有任何事件时判定链路已死并主动重连；"
                "Flandora 默认每 30 秒发一次心跳。"
            ),
            order=6,
        ),
    )
    action_timeout_sec: float = Field(
        default=DEFAULT_ACTION_TIMEOUT_SEC,
        description="单次动作请求的超时秒数。",
        json_schema_extra=_ui(
            label="动作超时",
            hint="发送消息等动作的等待上限，超时按失败处理。",
            order=7,
        ),
    )
    attachment_max_mb: int = Field(
        default=DEFAULT_ATTACHMENT_MAX_MB,
        description="读取本机附件转 base64 的大小上限（MB）。",
        json_schema_extra=_ui(
            label="附件大小上限（MB）",
            hint="入站图片、语音、文件超过该 MB 数时只保留文本占位，避免占用过多内存。",
            order=7,
        ),
    )

    @field_validator("server", mode="before")
    @classmethod
    def _normalize_server(cls, value: Any) -> str:
        """服务端地址留空时回退默认值。

        地址里若带上了协议前缀或路径会被剥掉，只取主机名。
        """

        normalized = _normalize_string(value)
        for prefix in ("ws://", "wss://", "http://", "https://"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        normalized = normalized.split("/", 1)[0]
        if ":" in normalized:
            normalized = normalized.split(":", 1)[0]
        return normalized or DEFAULT_SERVER_HOST

    @field_validator("port", mode="before")
    @classmethod
    def _normalize_port(cls, value: Any) -> int:
        """端口规整为正整数。"""

        return _normalize_positive_int(value, DEFAULT_SERVER_PORT)

    @field_validator("token", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        """文本字段去空白。"""

        return _normalize_string(value)

    @field_validator(
        "reconnect_delay_sec",
        "max_reconnect_delay_sec",
        "heartbeat_interval_sec",
        "action_timeout_sec",
        mode="before",
    )
    @classmethod
    def _normalize_delay(cls, value: Any, info: ValidationInfo) -> float:
        """时延字段规整为正浮点数；非法值回落到该字段自己的默认值。"""

        return _normalize_positive_float(value, _DELAY_DEFAULTS[info.field_name])

    @field_validator("attachment_max_mb", mode="before")
    @classmethod
    def _normalize_attachment_limit(cls, value: Any) -> int:
        """附件上限规整为正整数（单位 MB）。"""

        return _normalize_positive_int(value, DEFAULT_ATTACHMENT_MAX_MB)

    def build_ws_uri(self) -> str:
        """构造连向 Flandora 的 WebSocket 地址。

        Returns:
            str: 形如 ``ws://127.0.0.1:7999/`` 的地址；token 非空时附带
            ``access_token`` 查询参数（Flandora 的 WS 握手支持该参数）。
        """

        uri = f"ws://{self.server}:{self.port}/"
        if self.token:
            uri = f"{uri}?access_token={quote(self.token, safe='')}"
        return uri

    @property
    def attachment_max_bytes(self) -> int:
        """附件上限的字节数（配置项以 MB 为单位）。"""

        return self.attachment_max_mb * BYTES_PER_MB

    def connection_signature(self) -> tuple[str, int, str]:
        """返回决定是否需要重建连接的关键字段组合。"""

        return (self.server, self.port, self.token)


class FlandoraFilterConfig(PluginConfigBase):
    """入站消息过滤配置。"""

    __ui_label__: ClassVar[str] = "过滤"
    __ui_order__: ClassVar[int] = 2

    ignore_self_message: bool = Field(
        default=True,
        description="丢弃账号自己发出的消息。",
        json_schema_extra=_ui(
            label="忽略自己发出的消息",
            hint="微信账号手动发出的消息也会被 Flandora 上报；开启后这些消息不会进入麦麦。",
            order=0,
        ),
    )
    ban_user_id: List[str] = Field(
        default_factory=list,
        description="用户黑名单。",
        json_schema_extra=_ui(
            label="用户黑名单",
            hint="命中的发送者消息直接丢弃；支持纯 ID 或 platform:id 形式，一行一个。",
            order=1,
        ),
    )
    ban_group_id: List[str] = Field(
        default_factory=list,
        description="群黑名单。",
        json_schema_extra=_ui(
            label="群黑名单",
            hint="命中的群消息直接丢弃；支持纯 ID 或 platform:id 形式，一行一个。",
            order=2,
        ),
    )

    @field_validator("ban_user_id", "ban_group_id", mode="before")
    @classmethod
    def _normalize_ban_lists(cls, value: Any) -> List[str]:
        """黑名单规整为去重字符串列表。"""

        return _normalize_string_list(value)

    def is_user_banned(self, user_id: Any) -> bool:
        """判断发送者是否命中黑名单。"""

        return _matches_scoped_identifier(self.ban_user_id, str(user_id or ""))

    def is_group_banned(self, group_id: Any) -> bool:
        """判断群是否命中黑名单。"""

        return _matches_scoped_identifier(self.ban_group_id, str(group_id or ""))


class FlandoraNoticeConfig(PluginConfigBase):
    """通知事件开关。"""

    __ui_label__: ClassVar[str] = "通知事件"
    __ui_order__: ClassVar[int] = 3

    enable_group_recall: bool = Field(
        default=True,
        description="是否上报群撤回通知。",
        json_schema_extra=_ui(
            label="群撤回通知",
            hint="有人撤回群消息时上报一条通知，内容不含原文。",
            order=0,
        ),
    )
    enable_friend_recall: bool = Field(
        default=True,
        description="是否上报私聊撤回通知。",
        json_schema_extra=_ui(
            label="私聊撤回通知",
            hint="好友撤回私聊消息时上报一条通知，内容不含原文。",
            order=1,
        ),
    )
    enable_poke: bool = Field(
        default=True,
        description="是否上报拍一拍通知。",
        json_schema_extra=_ui(
            label="拍一拍通知",
            hint="有人拍一拍时上报一条通知。",
            order=2,
        ),
    )


class FlandoraDebugConfig(PluginConfigBase):
    """调试配置。"""

    __ui_label__: ClassVar[str] = "调试"
    __ui_order__: ClassVar[int] = 4

    log_raw_events: bool = Field(
        default=False,
        description="是否记录入站原始事件。",
        json_schema_extra=_ui(
            label="记录原始事件",
            hint="仅排查协议结构问题时开启；会把每条入站事件原文写进日志。",
            order=0,
        ),
    )


class FlandoraPluginSettings(PluginConfigBase):
    """Flandora 适配器完整配置。"""

    plugin: FlandoraPluginOptions = Field(default_factory=FlandoraPluginOptions)
    client: FlandoraClientConfig = Field(default_factory=FlandoraClientConfig)
    filters: FlandoraFilterConfig = Field(default_factory=FlandoraFilterConfig)
    notice: FlandoraNoticeConfig = Field(default_factory=FlandoraNoticeConfig)
    debug: FlandoraDebugConfig = Field(default_factory=FlandoraDebugConfig)

    def should_connect(self) -> bool:
        """当前配置下是否应当建立连接。"""

        return self.plugin.should_connect()

    def validate_runtime_config(self, logger: Any) -> bool:
        """校验启动连接的前提条件。

        Args:
            logger: 插件日志对象。

        Returns:
            bool: 满足启动条件时返回 ``True``，否则记录原因并返回 ``False``。
        """

        config_version = self.plugin.config_version
        if config_version != SUPPORTED_CONFIG_VERSION:
            logger.error(
                f"适配器配置版本不兼容：当前 {config_version}，"
                f"本插件要求 {SUPPORTED_CONFIG_VERSION}；"
                "请删除插件配置目录下的 config.toml 让宿主重新生成"
            )
            return False

        if not self.client.server:
            logger.warning("适配器已启用，但 client.server 为空")
            return False

        if self.client.port <= 0:
            logger.warning("适配器已启用，但 client.port 不是正整数")
            return False

        if self.client.max_reconnect_delay_sec < self.client.reconnect_delay_sec:
            logger.warning(
                "client.max_reconnect_delay_sec 小于 client.reconnect_delay_sec，"
                "将按重连初始间隔处理"
            )

        return True
