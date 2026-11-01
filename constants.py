"""Flandora 适配器常量与默认值。"""

from __future__ import annotations

FLANDORA_GATEWAY_NAME = "flandora_gateway"
FLANDORA_PLATFORM = "wechat"
FLANDORA_PROTOCOL = "flandora"

# 会话作用域：本插件只对接一个 Flandora 实例，固定取值可让会话 ID 跨重启保持稳定。
FLANDORA_SCOPE = "flandora"

SUPPORTED_CONFIG_VERSION = "1.0.0"

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 7999
DEFAULT_RECONNECT_DELAY_SEC = 5.0
DEFAULT_MAX_RECONNECT_DELAY_SEC = 60.0
DEFAULT_HEARTBEAT_INTERVAL_SEC = 30.0
DEFAULT_ACTION_TIMEOUT_SEC = 15.0
DEFAULT_ATTACHMENT_MAX_MB = 20
BYTES_PER_MB = 1024 * 1024

# 出站文件：宿主 1.3.16+ 会把 file 段的 file_ref 换成 http 签名地址，适配器要先落成本地
# 文件才能交给 Flandora。上限独立于 attachment_max_mb（那个只管入站内联），与宿主默认的
# max_file_mib 对齐；签名地址默认 300 秒过期，所以要尽快下完。
OUTBOUND_FILE_MAX_BYTES = 50 * BYTES_PER_MB
OUTBOUND_FILE_TIMEOUT_SEC = 60.0
OUTBOUND_FILE_CHUNK_BYTES = 64 * 1024
# 发送结果不明时（超时、连接断开）Flandora 可能仍在读文件，延迟清理。
OUTBOUND_FILE_CLEANUP_DELAY_SEC = 600.0

# 入站事件类型
POST_TYPE_MESSAGE = "message"
POST_TYPE_MESSAGE_SENT = "message_sent"
POST_TYPE_NOTICE = "notice"
POST_TYPE_META_EVENT = "meta_event"

# notice 类型
NOTICE_GROUP_RECALL = "group_recall"
NOTICE_FRIEND_RECALL = "friend_recall"
NOTICE_NOTIFY = "notify"
NOTIFY_POKE = "poke"

# 通知里的人名解析：单次查询的超时，查不到就回退数字 ID
NOTICE_NAME_TIMEOUT_SEC = 3.0

# 段类型
SEGMENT_TEXT = "text"
SEGMENT_AT = "at"
SEGMENT_IMAGE = "image"
SEGMENT_EMOJI = "emoji"
SEGMENT_FACE = "face"
SEGMENT_RECORD = "record"
SEGMENT_VIDEO = "video"
SEGMENT_FILE = "file"
SEGMENT_REPLY = "reply"
SEGMENT_FORWARD = "forward"
SEGMENT_NODE = "node"
SEGMENT_NODES = "nodes"

BASE64_URI_PREFIX = "base64://"
FILE_URI_PREFIX = "file://"
HTTP_PREFIXES = ("http://", "https://")

# 宿主侧组件类型名（与 OneBot 的段名不同，出入站编解码共用一份）
COMPONENT_TEXT = "text"
COMPONENT_AT = "at"
COMPONENT_IMAGE = "image"
COMPONENT_EMOJI = "emoji"
COMPONENT_VOICE = "voice"
COMPONENT_FILE = "file"
COMPONENT_REPLY = "reply"
COMPONENT_FORWARD = "forward"
