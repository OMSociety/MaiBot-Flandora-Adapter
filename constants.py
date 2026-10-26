"""Flandora 适配器常量与默认值。"""

from __future__ import annotations

APP_NAME = "flandora-adapter"
PLUGIN_ID = "omsociety.flandora-adapter"

FLANDORA_GATEWAY_NAME = "flandora_gateway"
FLANDORA_PLATFORM = "wechat"
FLANDORA_PROTOCOL = "flandora"

SUPPORTED_CONFIG_VERSION = "1.0.0"

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 7999
DEFAULT_CONNECTION_ID = "flandora_default"
DEFAULT_RECONNECT_DELAY_SEC = 5.0
DEFAULT_MAX_RECONNECT_DELAY_SEC = 60.0
DEFAULT_HEARTBEAT_INTERVAL_SEC = 30.0
DEFAULT_ACTION_TIMEOUT_SEC = 15.0
DEFAULT_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_SELF_ID_CACHE_PATH = "data/flandora_self_id.json"

# OneBot v11 retcode：与 Flandora flandora/action_catalog.py 的取值保持一致。
RETCODE_OK = 0
RETCODE_BAD_PARAM = 1400
RETCODE_AUTH_FAILED = 1401
RETCODE_NOT_IMPLEMENTED = 1404
RETCODE_UNSUPPORTED = 1405
RETCODE_NOT_FOUND = 1406
RETCODE_INTERNAL = 1500

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

# meta_event 类型
META_HEARTBEAT = "heartbeat"
META_LIFECYCLE = "lifecycle"

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
