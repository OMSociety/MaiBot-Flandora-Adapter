# 配置说明

配置分五节，全部带默认值，通常只需要改 `[client]`。在麦麦面板的插件配置页填写，或直接编辑插件目录下的 `config.toml`。

## `[plugin]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 插件总开关；设为 `false` 时插件只登记组件并保持静默，改回 `true` 后重新连接 |
| `config_version` | `str` | `1.0.0` | 配置结构版本，由插件维护；与本插件要求的版本不一致时拒绝启动连接 |

## `[client]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `server` | `str` | `127.0.0.1` | OneBot 服务端地址，可带 `ws://` 前缀；端口统一写在 `port` 里，两处不一致会报配置错误 |
| `port` | `int` | `7999` | OneBot 服务端端口，对应 Flandora 的 `ob_server_port` |
| `token` | `str` | 空 | 与 Flandora 的 `ob_server_token` 一致；非空时以 `?access_token=` 附在连接地址上 |
| `reconnect_delay_sec` | `float` | `5.0` | 断线后的初始重连间隔，每次失败翻倍 |
| `max_reconnect_delay_sec` | `float` | `60.0` | 重连间隔的退避上限 |
| `heartbeat_interval_sec` | `float` | `30.0` | 空闲阈值：超过该值两倍、再宽限 5 秒仍没有任何事件就主动重连 |
| `action_timeout_sec` | `float` | `15.0` | 单个动作请求的等待上限，超时按失败处理 |
| `attachment_max_mb` | `int` | `20` | 单个附件内联上限（MB）；超限的附件退化为占位文本，其余段照常送达 |

## `[filters]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ignore_self_message` | `bool` | `true` | 挡掉自己在微信客户端手发的消息，避免麦麦自问自答 |
| `ban_user_id` | `list` | 空 | 用户黑名单，命中即不入站；可填整数 ID 或 wxid |
| `ban_group_id` | `list` | 空 | 群黑名单，命中即不入站；可填整数 ID 或群 wxid（`xxx@chatroom`） |
| `quote_wakes` | `bool` | `true` | 引用必回复：引用机器人自己发出的消息时按被 @ 处理；关闭后只按真实的 @ 与提及判断 |

## `[notice]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable_group_recall` | `bool` | `true` | 群成员撤回消息时上报一条通知，内容不含原文 |
| `enable_friend_recall` | `bool` | `true` | 好友撤回私聊消息时上报一条通知，内容不含原文 |
| `enable_poke` | `bool` | `true` | 有人拍一拍时上报一条通知 |

通知文本里的人名由适配器按 ID 现查（群内走 `get_group_member_info`，好友走 `get_stranger_info`），单次查询超过 3 秒或 Flandora 回 `1406` 时回退成数字 ID。撤回通知带 `[事件-xxx]` 前缀；拍一拍按微信原句输出。

## `[debug]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `log_raw_events` | `bool` | `false` | 把 Flandora 推送的原始事件写进日志（超长截断），排查协议结构时开启 |

## 模板

```toml
[plugin]
enabled = true
config_version = "1.0.0"

[client]
server = "127.0.0.1"
port = 7999
token = ""
reconnect_delay_sec = 5.0
max_reconnect_delay_sec = 60.0
heartbeat_interval_sec = 30.0
action_timeout_sec = 15.0
attachment_max_mb = 20

[filters]
ignore_self_message = true
ban_user_id = []
ban_group_id = []
quote_wakes = true

[notice]
enable_group_recall = true
enable_friend_recall = true
enable_poke = true

[debug]
log_raw_events = false
```
