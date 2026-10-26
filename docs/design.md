# Flandora 适配器设计文档

本文件是本插件的设计依据：记录两侧契约、关键取舍、数据映射与已知缺口。改动实现时同步改本文件。

## 1. 定位

本插件是 MaiBot（麦麦）的平台适配器，通过 OneBot v11 正向 WebSocket 连接 [Flandora](https://github.com/OMSociety/Flandora)，把微信个人号的群聊与私聊接入麦麦，并把麦麦的回复发回微信。

职责边界遵循 Flandora 的桥接定位：本插件只做通道与协议翻译，不在适配器里决定"要不要回"（@ 过滤、上下文拼接、概率决策都由麦麦完成）。微信侧消息一律如实上报，被 @ 只做标记。

## 2. 两侧契约

### 2.1 Flandora 侧

Flandora 是 OneBot v11 服务端；本插件是正向 WS 客户端。以下事实取自 `D:\WorkSpace\Github\Flandora` 的源码与文档。

**连接**

| 项 | 值 | 来源 |
|---|---|---|
| 默认地址 | `127.0.0.1:7999` | `flandora/config/store.py` |
| 默认 token | 空 | 同上 |
| 默认消息格式 | `ob_message_format = "array"` | 同上 |

**事件**

`post_type` 取值为 `message`、`message_sent`、`meta_event`（`heartbeat`、`lifecycle`）、`notice`（`group_recall`、`friend_recall`、`notify` + `sub_type=poke`）。

消息事件字段（`flandora/ob_protocol.py` 的 `render_message_event`）：

```
time, self_id, post_type, message_id, message_type(group|private),
group_id, group_wxid, user_id, message(段数组), raw_message(CQ 串),
sender{user_id, nickname, wxid}
```

群消息额外带 `group_name` 与 `is_mentioned`（是否真实 @ 了机器人）。

**ID 约定**

Flandora 对外只暴露 32 位正整数 ID，wxid 与整数的双向映射落在 `data/id_map.json`，重启与升级不变。写侧只接受映射表已分配过的号，没见过返回 `1406`；发送目标也可以直接填 wxid / `xxx@chatroom`。

**段格式**（`to_segment_dict`）

| 段 | data |
|---|---|
| `text` | `{text}` |
| `at` | `{qq}`；无整数 ID 时 `{qq:"", name}` |
| `image` / `emoji` | `{file}` |
| `face` | `{id}` |
| `record` / `video` | `{file}` |
| `file` | `{file, name}` |
| `reply` | `{id}` |

图片内联阈值 `MAX_INLINE_IMAGE_BYTES = 4 MiB`：不超过则给 `base64://…`，超过则给 `file:///D:/…` 本地文件 URI。

**发送动作**

`send_msg` / `send_private_msg` / `send_group_msg`，参数 `message_type`、`user_id`、`group_id`、`message`、`auto_escape`。

返回值：

- 至少一段发出：`{"status": "ok", "retcode": 0, "data": {"message_id": <int>}}`
- 部分段失败：在 `data` 上追加 `failed_segments` 与 `failed_details`
- 一段都没发出：`{"status": "failed", "retcode": <1500|1404|1400>, "message": "…"}`

**能力限制**

`reply` 段在发送侧被跳过（整条只有 reply 时返回 1404）；`file` 段只接受本机路径、`file://` 与 `base64://`，http(s) 链接不下载；`record` 降级为 mp3 文件、`video` 降级为文件；`node` / `nodes` 不接受；`@全体` 被拒绝。

**被引消息是机器人自己时**，Flandora 已在段数组最前面插入一个 at 自己的段（`flandora/bridge_core.py`）。

**retcode**：0 成功、1400 参数错、1401 鉴权失败、1404 未实现、1405 不支持、1406 未找到、1500 内部错。

### 2.2 MaiBot 侧

宿主为 MaiBot 1.3.15，SDK 为 maibot_sdk 2.16.0。宿主源码位于安装目录的 `.onekey/environments/<snapshot>/Lib/site-packages/src/`，下文以 `src/` 指代。

**manifest**

必填字段：`manifest_version`(=2)、`id`、`version`（严格三段式）、`name`、`description`、`author`、`license`、`urls`、`host_application`、`sdk`、`capabilities`、`i18n`。可选：`dependencies`、`llm_providers`、`plugin_type`、`display`、`changelog`。

`src/plugin_runtime/runner/manifest_validator.py` 的模型是严格模式（`extra="forbid"`），历史字段（`homepage_url`、`min_version`、`sdk_version` 等）出现即校验失败。`id` 必须用点号或横线分隔。`license` 无枚举限制。`display.icon.type = "local"` 时路径必须是插件目录内的相对路径，后缀限 jpg/jpeg/png/svg/webp。

**网关组件**

`@MessageGateway(name=…, route_type=…, platform=…, protocol=…, description=…)`，`route_type` 只能是 `send`、`receive`、`duplex`（`maibot_sdk/components.py`）。

出站 handler 签名与返回：

```python
async def handler(self, message: Dict[str, Any], route: Optional[Dict[str, Any]] = None,
                  metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]
```

成功返回 `{"success": True, "external_message_id": <str|None>, "metadata": {...}}`；失败返回 `{"success": False, "error": <str>, "metadata": {...}}`。宿主从 `external_message_id` 或 `message_id` 取平台消息号构造投递回执（`src/platform_io/drivers/plugin_driver.py`）。

**消息号回填**

成功返回里附：

```python
"metadata": {"adapter_callbacks": [{"name": "message_id_echo",
              "payload": {"content": {"type": "echo", "echo": <内部 id>, "actual_id": <外部 id>}}}]}
```

宿主 `src/chat/message_receive/bot.py` 的 `echo_message_process` 据此更新内部 message_id。

**入站推送**

```python
accepted = await self.ctx.gateway.route_message(
    gateway_name=…, message=<message_dict>,
    external_message_id=…, dedupe_key=…)
```

`message_dict` 必需字段：`message_id`（非空 str）、`platform`（非空 str）、`message_info`（dict）、`raw_message`（list）。可选：`timestamp`（float 字符串）、`account_id`、`scope`、`is_mentioned`、`is_at`、`is_emoji`、`is_picture`、`is_command`、`is_notify`（均 bool）、`session_id`、`reply_to`、`processed_plain_text`。

`message_info` 中：`user_info` 必须有非空的 `user_id` 与 `user_nickname`；`group_info` 若给出必须有非空 `group_id`（`group_name` 允许空串）；`additional_config` 默认 `{}`（`src/plugin_runtime/host/message_utils.py`）。

**入站组件格式**（与 OneBot 段不同，需逐项翻译）

| 组件 | data |
|---|---|
| `text` | 裸字符串 |
| `image` / `emoji` / `voice` | `data` 为 content 字符串，另有 `hash`、`binary_data_base64` |
| `file` | payload dict |
| `at` | `{target_user_id, target_user_nickname, target_user_cardname}` |
| `reply` | `{target_message_id, target_message_content, target_message_sender_id, target_message_sender_nickname, target_message_sender_cardname}` |
| `forward` | 节点数组 |

**出站组件格式**（`src/plugin_runtime/host/message_utils.py`）

| 组件 | 形态 |
|---|---|
| `text` | `{"type": "text", "data": <str>}` |
| `image` / `emoji` / `voice` | `{"type": …, "data": content, "hash": …, "binary_data_base64": …}` |
| `file` | `{"type": "file", "data": FileComponent.to_payload()}` |
| `at` / `reply` | 同入站字段 |

`FileComponent` 的字段是 `name`、`size`、`url`、`file_id`、`mime_type`、`base64_data`，**没有本地路径字段**（`src/common/data_models/message_component_data_model.py`）。

**提及判定**

`src/chat/utils/utils.py` 的 `is_mentioned_bot_in_message` 按序检测：`additional_config.at_bot`（命中即把回复概率置 1.0）或 `additional_config.is_mentioned` → 消息上的 `is_at` / `is_mentioned` → 段里的 `mention_bot` → 扫段找目标为机器人账号的 `AtComponent` → 文本正则 → 回复痕迹正则 → 昵称与别名匹配。

**账号上报**

适配器必须上报机器人账号，否则宿主认为该平台未配置机器人账号，`is_bot_self` 失效、@ 判定失效：

```python
await self.ctx.gateway.update_state(
    gateway_name=…, ready=True, platform="wechat",
    account_id=<self_id>, scope=<连接标识>, metadata={…})
```

**通知消息**

适配器构造 `is_notify=True` 的 message_dict，文本由适配器完整格式化（含 `[事件-xxx]` 前缀），`additional_config` 需为 dict；宿主只做类型识别（`src/chat/message_receive/bot.py` 的 `handle_notice_message`）。

**宿主入站链没有自我过滤**

`src/plugin_runtime/host/message_gateway.py` 的 `receive_external_message` 只做格式转换后交给 `chat_bot.receive_message`；宿主内核不感知 OneBot 的 `post_type`（`src/` 内 grep 零结果），也没有"发送者是自己就丢弃"的判断（`is_self` / `own_message` 在 `chat`、`plugin_runtime`、`common` 内零结果）。

## 3. 关键设计决策

### 3.1 `message_sent` 一律丢弃

Flandora 的 `message_sent` 是机器人自己发出消息的镜像事件（`make_sent_event`；私聊时 `user_id` 是对方，`sender.user_id` 才是自己）。

丢弃的理由：

1. 宿主侧没有任何自我过滤（见 §2.2 末条）。上抛后，麦麦会把自己刚说的话当成一条新收到的消息写入会话历史并送进决策层，等于每发一条就多读一遍自己的话，可能自我触发回复。
2. "被引用时该醒"不需要它——Flandora 在被引消息是机器人自己时已补 at 段，本插件按 at 段设 `additional_config.at_bot = True`，宿主即给 100% 回复概率。
3. "自己发出消息的号"也不需要它——Flandora 的 `send_*` 响应直接返回 `data.message_id`，本插件走 `adapter_callbacks` 的 `message_id_echo` 回填。

代价：用户在 Flandora 面板里替机器人发的消息，麦麦看不见（见 §9）。

本决策不提供配置开关。

### 3.2 出站 `reply` 段丢弃

Flandora 的发送侧本来就不能构造微信的引用回复（`reply` 段被跳过），只发 reply 时整条返回 1404。适配器在出站阶段直接丢弃 `reply` 段、其余段照常发，避免"整条只有 reply 时必然失败"。

### 3.3 图片与文件的本机读取

Flandora 对超过 4 MiB 的图片给 `file:///D:/…` 本地 URI，`file` 段也只接受本机路径 / `file://` / `base64://`。因此本适配器在入站时直接读这些本地文件并转成 base64，在出站时把宿主给的 base64 转成 `base64://` 段。

这要求麦麦与 Flandora 在同一台机器上运行。跨机部署时图片、语音、文件会退化成文本占位（见 §9）。

适配器**不代 Flandora 下载 http(s) 链接**：既不越过 Flandora "不替客户端访问网络"的边界，也避免把 URL 下载变成 SSRF 面。

### 3.4 自己在微信里手发的消息按配置过滤

微信账号手动发出的消息会被 Flandora 作为 `message` 事件上报（`user_id` 等于 `self_id`）。默认丢弃（`filters.ignore_self_message = true`），避免麦麦把自己的话当成用户消息。该开关可关，关掉后这些消息会作为普通用户消息进入麦麦。

## 4. 配置模型

配置分节如下，`plugin.config_version` 是版本闸，配置结构变更时必须同步提升。

| 节 | 字段 | 默认 | 说明 |
|---|---|---|---|
| `plugin` | `enabled` | `true` | 插件总开关 |
| | `config_version` | `"1.0.0"` | 隐藏项，版本闸 |
| `client` | `server` | `"127.0.0.1"` | Flandora 地址 |
| | `port` | `7999` | OneBot v11 端口 |
| | `token` | `""` | access_token，可空 |
| | `connection_id` | `"flandora_default"` | 作 `scope` 上报，并用于日志标识 |
| | `reconnect_delay_sec` | `5.0` | 首次重连间隔 |
| | `max_reconnect_delay_sec` | `60.0` | 指数退避上限 |
| | `heartbeat_interval_sec` | `30.0` | 静默看护阈值 |
| | `action_timeout_sec` | `15.0` | 单次 action 超时 |
| | `attachment_max_bytes` | `20971520` | 读本地附件转 base64 的上限，超过则文本占位 |
| | `self_id_cache_path` | `"data/flandora_self_id.json"` | self_id 兜底缓存 |
| `filters` | `ignore_self_message` | `true` | 丢弃 `user_id == self_id` 的入站消息 |
| | `ban_user_id` | `[]` | 用户黑名单，兼容 `platform:id` 与纯 id |
| | `ban_group_id` | `[]` | 群黑名单，同上 |
| `notice` | `enable_group_recall` | `true` | 群撤回通知 |
| | `enable_friend_recall` | `true` | 私聊撤回通知 |
| | `enable_poke` | `true` | 拍一拍通知 |
| `debug` | `log_raw_events` | `false` | 打印原始 WS 载荷 |

会话黑白名单不在这里做：宿主侧的 `adapter_policy` 已经管这一层。

## 5. 入站链路

### 5.1 顶层 message_dict

```python
{
  "message_id": str(event["message_id"]),
  "platform": "wechat",
  "account_id": str(event["self_id"]),
  "scope": settings.client.connection_id or None,
  "timestamp": str(float(event["time"])),
  "message_info": {
      "user_info": {"user_id": str(event["user_id"]),
                    "user_nickname": event["sender"]["nickname"] or str(event["user_id"]),
                    "user_cardname": None},
      "group_info": ({"group_id": str(event["group_id"]),
                      "group_name": event.get("group_name") or ""}
                     if event["message_type"] == "group" else None),
      "additional_config": {"at_bot": <bool>, "is_mentioned": <bool>,
                            "flandora_wxid": event["sender"].get("wxid", ""),
                            "flandora_group_wxid": event.get("group_wxid", "")},
  },
  "raw_message": [...],
  "is_mentioned": <bool>, "is_at": <bool>,
  "is_picture": <bool>, "is_command": False,
}
```

`at_bot` 为真当且仅当段数组里存在指向 `self_id` 的 at 段，或事件的 `is_mentioned` 为真。

推送时以 `external_message_id = str(message_id)`、`dedupe_key = "msg:" + str(message_id)` 调用 `route_message`。

### 5.2 段映射（OneBot → 宿主）

| Flandora 段 | 宿主组件 |
|---|---|
| `text{text}` | `{"type": "text", "data": text}` |
| `at{qq}`（qq 为整数） | `{"type": "at", "data": {"target_user_id": str(qq), "target_user_nickname": None, "target_user_cardname": None}}` |
| `at{qq:"", name}` | 退成 `text` 段 `@name` |
| `image{file:"base64://…"}` | 解出字节 → `{"type": "image", "data": file, "hash": sha256, "binary_data_base64": b64}` |
| `image{file:"file:///…"}` 或本机路径 | 读盘后同上；读不到则 `text` 占位 `[图片]` |
| `face{id}` | `{"type": "text", "data": "[表情 id]"}` |
| `record{file}` | 读盘 → `{"type": "voice", "data": file, "binary_data_base64": b64}`；读不到则 `[语音]` |
| `video{file}` | `text` 占位 `[视频]` |
| `file{file, name}` | 未超 `attachment_max_bytes` → `{"type": "file", "data": {"name": name, "base64": b64}}`；超限则 `text` 占位 `[文件] name` |
| `reply{id}` | `{"type": "reply", "data": {"target_message_id": str(id)}}` |
| 未知类型 | `text` 占位 `[不支持的段 <type>]` 并记 warning |

### 5.3 notice 事件

统一构造 `is_notify=True` 的 message_dict，`raw_message` 只放一条适配器格式化的文本：

- `notice/group_recall` → `[事件-群撤回] <operator> 撤回了 <user> 的消息（message_id=<mid>）`
- `notice/friend_recall` → `[事件-私聊撤回] <operator> 撤回了 <user> 的消息（message_id=<mid>）`
- `notice/notify` + `sub_type=poke` → `[事件-戳一戳] <user> 戳了戳 <target>`

`message_id` 用 `f"flandora-notice-{时间戳}-{短哈希}"` 合成，`dedupe_key` 取事件自身特征串以保证幂等。`user_info.user_id` 取事件里的操作者，昵称缺失时回落 `str(user_id)`。群事件带 `group_info`。`additional_config` 放 `flandora_notice_type`、`flandora_notice_sub_type`、`flandora_notice_payload`。

### 5.4 过滤

先按 `post_type` 白名单（只处理 `message`、`notice`、`meta_event`），再按配置：`ignore_self_message`、`ban_user_id`、`ban_group_id`、`notice.enable_*`。

## 6. 出站链路

### 6.1 动作选择

群消息（`group_info.group_id` 非空）→ `send_group_msg`，参数 `{"group_id": int(group_id), "message": [段…]}`；私聊 → `send_private_msg`，参数 `{"user_id": int(user_id), "message": [段…]}`。

两个 ID 都来自入站时写入的 Flandora 整数 ID，出站原样回填。若不是纯数字，直接返回失败并说明原因。

### 6.2 段映射（宿主 → OneBot）

| 宿主组件 | Flandora 段 |
|---|---|
| `text{data: str}` | `{"type": "text", "data": {"text": str}}` |
| `at{target_user_id}` | 纯数字 → `{"type": "at", "data": {"qq": int}}`；否则跳过并记 warning |
| `image`（有 `binary_data_base64`） | `{"type": "image", "data": {"file": "base64://" + b64}}` |
| `image`（`data` 是 `file://` 或本机路径） | 原样透传该字符串 |
| `image`（只给了 http(s) 链接） | 跳过 + warning + 计入失败详情 |
| `voice`（有二进制） | `{"type": "record", "data": {"file": "base64://" + b64}}` |
| `file{base64}` | `{"type": "file", "data": {"file": "base64://" + b64, "name": name}}` |
| `file{url 是 file:// 或本机路径}` | `{"type": "file", "data": {"file": url, "name": name}}` |
| `file{url 是 http(s)}` 或无内容 | 降级成 `text` 段 `[文件] name` 并计入失败详情 |
| `reply` | 丢弃（见 §3.2） |
| `emoji` | 按图片处理 |
| `forward` | 展开：节点内的文本段顺序拼成 text 段，非文本节点降级为占位文本；不产出 `node` / `nodes` |
| 其它类型 | 跳过 + warning |

段数组为空（例如整条只有 reply）时不发动作，直接返回失败。

### 6.3 handler 返回

```python
# 至少一段发出
{"success": True,
 "external_message_id": str(resp["data"]["message_id"]),
 "metadata": {"action": "send_group_msg",
              "actions": ["send_group_msg"],
              "failed_segments": resp["data"].get("failed_segments", 0),
              "failed_details": resp["data"].get("failed_details", []),
              "adapter_callbacks": [{"name": "message_id_echo",
                                     "payload": {"content": {"type": "echo",
                                                             "echo": internal_message_id,
                                                             "actual_id": external_message_id}}}]}}

# 失败
{"success": False, "error": <原因>, "metadata": {"action": …, "retcode": …}}
```

成功判定为 `status == "ok" and retcode == 0`。Flandora 在一段都没发出时一定返回 `status: "failed"`，因此不会把未送达当成功。`failed_segments > 0` 时整体仍算成功（部分段已送达），但记 warning 并如实写进 `metadata`。

## 7. 连接生命周期

1. `on_load`：读配置，`plugin.enabled` 为真则启动连接任务，否则只登记组件。
2. 连接 `ws://{server}:{port}`，token 非空时挂 URL 查询参数。
3. 连上后调 `get_login_info` 取 `self_id` 与昵称，写 `self_id_cache_path` 作兜底；随后 `update_state(ready=True, platform="wechat", account_id=str(self_id), scope=connection_id, metadata={"ws_url": …})`。
4. 读循环分派 `message`、`notice`、`meta_event`；`heartbeat` 只刷新最后活跃时间，`lifecycle` 记日志。
5. 看护协程：超过 `heartbeat_interval_sec * 2` 无任何事件即主动重连；重连间隔从 `reconnect_delay_sec` 起指数退避到 `max_reconnect_delay_sec`。
6. 断开时 `update_state(ready=False, platform="wechat")`，重连成功后重新上报。
7. `on_config_update(scope, config_data, version)`：`scope == "self"` 时，连接参数（`server`/`port`/`token`/`connection_id`/`enabled`）变化才重建连接；只改 `filters`、`notice`、`debug` 则热更新。
8. `on_unload`：关连接、取消后台任务、上报 `ready=False`。

## 8. 边界与失败模式

| 情况 | 行为 |
|---|---|
| Flandora 未启动或端口不通 | 记 warning 并退避重连；插件不崩溃，麦麦正常启动 |
| token 错误 | 记 error 并给出排查方向，继续退避重试 |
| action 超时 | 到 `action_timeout_sec` 即判失败；迟到的响应按 echo id 丢弃 |
| `retcode=1406` | 失败返回并提示该 ID 未在 Flandora 映射表分配过 |
| `retcode=1404` | 失败返回，error 文案带 Flandora 返回的 wording |
| 附件超过 `attachment_max_bytes` | 文本占位，日志记原始大小 |
| `file://` 指向的文件读不到 | 文本占位，不抛异常 |
| 段数组含未知类型 | 占位文本 + warning，不整条丢 |
| 同一条消息重复到达 | 由 `dedupe_key` 交给宿主去重 |
| 尚未拿到 `self_id` | 入站事件自带 `self_id`，以事件为准；上报用缓存兜底 |
| Flandora 侧微信掉线（`get_status.online=false`） | 记 warning 并保持 WS 连接，等待恢复 |

## 9. 已知缺口

- 引用块内容不完整：入站 `reply` 段只填 `target_message_id`，不调 `get_msg` 补原文。"引用了机器人"的唤醒由 Flandora 补的 at 段承载，不受影响。
- 出站 `reply` 段丢弃（见 §3.2）。
- 出站 http(s) 链接形式的图片与文件不发（见 §3.3）。
- `message_sent` 一律丢弃：用户在 Flandora 面板里替机器人发的消息，麦麦看不见（见 §3.1）。
- Flandora 未实现的能力（群管理、好友管理、消息撤回、合并转发、@全体等）本插件不暴露。
- `video` 段只做文本占位，不搬运视频本体。
- 语音与视频本体按 Flandora 实况处理（可能只收到文本占位），编解码两条路都留了实现。
- 跨机部署不支持（见 §3.3）。
