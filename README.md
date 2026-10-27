# MaiBot-Flandora-Adapter

Flandora（微信个人号 OneBot v11 桥接器）与 MaiBot（麦麦）之间的消息网关适配器。
装好之后，麦麦可以在微信里收发群聊与私聊消息。

## 工作原理

Flandora 把微信个人号暴露成一个 OneBot v11 服务端；本插件作为 WebSocket 客户端连上去，
把 OneBot 事件翻译成麦麦的消息网关事件，再把麦麦的回复翻译成 OneBot 动作请求发回去。

| 角色 | 职责 |
| --- | --- |
| Flandora | 读微信本地库收消息、走 Windows UI 自动化发消息、维护 wxid 与整数 ID 的映射 |
| 本插件 | 事件与消息段的双向翻译、连接维护、账号上报 |
| MaiBot | 会话管理、上下文与人格、决定回不回以及回什么 |

```
微信 ←→ Flandora ←─ WebSocket(OneBot v11) ─→ 本插件 ←→ MaiBot
```

> **提示**：本插件在 Flandora 上的定位与 AstrBot 的 `aiocqhttp` 适配器相同——都是「客户端主动连过去」。
> 采用这种接法时，Flandora 侧保持默认的单节点即可。

## Flandora 侧配置

本插件连的是 Flandora 的 OneBot v11 **服务端入口**（`type = "ws_server"`），地址取插件配置里的
`server` / `port` / `token`。在 Flandora 控制台（默认 `http://127.0.0.1:4950`）里把三项对上即可：

| Flandora 配置项 | 默认值 | 与本插件的关系 |
| --- | --- | --- |
| `ob_server_host` | `127.0.0.1` | 对应插件的 `server`；同机部署保持回环 |
| `ob_server_port` | `7999` | 对应插件的 `port` |
| `ob_server_token` | 空 | 对应插件的 `token`；两边要么都留空，要么填同一串字符 |
| `ob_message_format` | `array` | 保持默认，本插件的段编解码按 `array` 实现 |
| `ob_networks` | 空 | 留空即可 |

`ob_networks` 留空时，Flandora 按上面三项自动起一个名为 `default` 的服务端入口，启动日志里会出现：

```
[OB11] WS 服务端 default 监听 127.0.0.1:7999/（role=universal，token=无）
```

若 `ob_networks` 里已经写了自定义入口，就在其中保留一个 `type = "ws_server"` 的入口：

- `port` 必填，`host` 不填按 `127.0.0.1`；
- `role` 填 `universal`（不填即 `universal`）：`api` 只处理动作请求、`event` 只推事件，本插件收发两个方向都用；
- `path` 不填即 `/`，与插件的连接地址 `ws://<host>:<port>/` 一致；填了别的路径时两者要相同。

反向 WS（`type = "ws_client"`）是「Flandora 主动去连框架的 WS 服务端」的入口，供 AstrBot 的
`aiocqhttp` 这类自己开服务端的框架使用；本插件是主动连过来的一方，不需要它。

收件方向还依赖 Flandora 能读到微信本地库。若它的日志里反复出现
`本地库收件源启动失败：找不到微信口令文件 ...\data\wx_key.dat`，说明取钥还没做：这时连接能建立、
发消息也正常，但收不到微信里的消息。到控制台走一遍「取钥向导」即可，之后 Flandora 会自行恢复。

## 环境要求

| 项 | 要求 |
| --- | --- |
| MaiBot | 1.3.0 – 1.3.99 |
| 插件 SDK | 2.7.0 – 2.99.99 |
| Flandora | 当前版本（OneBot v11 服务端；`message` 事件带 `message_id` 与 `group_wxid`，段格式为 `array`） |
| Python | 3.12 及以上（随麦麦运行环境，无需另装） |
| 依赖 | `websockets >= 12.0`（宿主会按 `_manifest.json` 自动安装） |

Flandora 侧的 `ob_message_format` 请保持默认的 `array`——本插件的段编解码按 `array` 实现，
`string` 形态的 CQ 串会让消息段无法解析。

## 安装

1. 把整个插件目录放到麦麦的插件目录下，目录名建议 `flandora-adapter`：

   ```
   <麦麦目录>/plugins/flandora-adapter/
   ```

2. 启动或重载麦麦，插件会在插件列表里以「Flandora 微信适配器」出现。
3. 按上一节把 Flandora 侧的三项对上，并在插件配置面板确认 Flandora 的监听地址与端口（默认 `127.0.0.1:7999`）。
4. 确认 Flandora 已启动、微信已登录。连接建立后，插件会向麦麦上报机器人账号，日志里会出现
   `消息网关已激活路由：platform=wechat account_id=... scope=...`。

## 配置

配置分五节，全部有默认值，通常只需要改 `[client]`。

### `[plugin]`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 插件总开关；设为 `false` 时插件只登记组件、保持静默，改回 `true` 后重新连接 |
| `config_version` | `1.0.0` | 配置结构版本，由插件维护，不要手改 |

### `[client]`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `server` | `127.0.0.1` | Flandora 的 OneBot 服务端地址；`ws://` 前缀与路径会被剥掉，端口请写在 `port` 里（两处不一致会报配置错误） |
| `port` | `7999` | Flandora 的 OneBot 服务端端口 |
| `token` | 空 | 与 Flandora 的 `ob_server_token` 一致；非空时以 `?access_token=` 附在连接地址上 |
| `reconnect_delay_sec` | `5.0` | 断线后的初始重连间隔 |
| `max_reconnect_delay_sec` | `60.0` | 重连间隔退避上限 |
| `heartbeat_interval_sec` | `30.0` | 空闲阈值：超过该值两倍、再宽限 5 秒仍没有任何事件就判定链路已死并主动重连 |
| `action_timeout_sec` | `15.0` | 单个动作请求的等待上限 |
| `attachment_max_mb` | `20` | 单个附件内联上限（MB）；超限的附件退化为占位文本，其余段照常送达 |

### `[filters]`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `ignore_self_message` | `true` | 在入站阶段挡掉自己在微信客户端手发的消息，避免麦麦自问自答 |
| `ban_user_id` | 空 | 用户黑名单，命中的消息在入站阶段过滤掉；可填整数 ID 或 wxid |
| `ban_group_id` | 空 | 群黑名单，命中的消息在入站阶段过滤掉；可填整数 ID 或群 wxid（`xxx@chatroom`） |
| `quote_wakes` | `true` | 引用必回复：引用机器人自己发出的消息时按「被提及」处理，回复概率拉满；关闭后只按真实的 @ 与提及判断 |

### `[notice]`

撤回与戳一戳的入站通知开关，三项默认全开：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enable_group_recall` | `true` | 群成员撤回消息 |
| `enable_friend_recall` | `true` | 好友撤回消息 |
| `enable_poke` | `true` | 戳一戳 |

通知文本里的人名由适配器按 ID 现查（群内走 `get_group_member_info`，好友走 `get_stranger_info`），
单次查询超过 3 秒或 Flandora 回 `1406` 时回退成数字 ID。撤回通知带 `[事件-xxx]` 前缀；
拍一拍按微信原句输出，被拍的是机器人时写成「张三 拍了拍 你」，带自定义文案时接在原句后面
（「张三 拍了拍 你的小肚子」）。

### `[debug]`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `log_raw_events` | `false` | 把 Flandora 推送的原始事件写进日志（超长截断），排查格式问题时开启 |

## 支持的消息段

**入站（微信 → 麦麦）**

| OneBot 段 | 处理方式 |
| --- | --- |
| `text` | 原文传入 |
| `at` | 转成麦麦的 `at` 段，并据此置位「是否 @ 了机器人」 |
| `image` / `emoji` | 解码或读盘后作为图片传入，同时计算哈希 |
| `face` | 转成文本 `[表情 id]` |
| `record` | 转成麦麦的语音段 |
| `file` | 未超上限时以文件段传入（含文件名与内容） |
| `reply` | 以引用段传入，携带被引消息的 `message_id`；被引的是机器人自己发的消息时（事件上的 `reply_to_self`）按「被提及」处理，正文不改写 |
| `video`、合并转发、其它 | 转成占位文本，其余段照常送达 |

**出站（麦麦 → 微信）**

| 麦麦段 | 处理方式 |
| --- | --- |
| `text` | 原文发送（微信侧逐字投递并回读校验） |
| `at` | 数字 ID 发真 @；其它形态记入失败详情 |
| `image` / `emoji` | 内联字节直接发送；本机路径按文件名到 Flandora 的附件目录里取件 |
| `voice` | 以语音文件发送 |
| `file` | 内联字节或本机路径直接发送 |
| 合并转发 | 展开为 `[合并转发]` 段落文本后发送 |

出站目标（群或私聊）取自宿主下发的目标信息，必须是 Flandora 分配过的整数 ID；
目标号缺失时这条消息直接失败，错误信息里给出原因。

## 开发与测试

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest tests -q
python -m compileall -q .
```

测试在普通 Python 环境即可运行；涉及宿主 SDK 的用例在 `maibot_sdk` 可导入时执行。

## 许可证与致谢

本项目以 AGPL-3.0-or-later 发布，全文见 [`LICENSE`](LICENSE)。

实现过程中参考了同为麦麦适配器的
[MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)（GPL-3.0-or-later）的
插件骨架、配置写法与消息段编解码取舍。
