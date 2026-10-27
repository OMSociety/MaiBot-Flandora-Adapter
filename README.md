<p align="center">
  <img src="https://raw.githubusercontent.com/OMSociety/MaiBot-Flandora-Adapter/main/assets/icon.svg" width="96" alt="Flandora 微信适配器" />
</p>

<h1 align="center">Flandora 微信适配器</h1>

<p align="center">把 Flandora 桥接的微信个人号接进 MaiBot：群聊与私聊的收发、引用、撤回与拍一拍都在麦麦里看得见。</p>

<p align="center">
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter"><img src="https://img.shields.io/badge/version-1.0.0-07C160" alt="版本"></a>
  <a href="https://github.com/OMSociety/MaiBot"><img src="https://img.shields.io/badge/MaiBot-1.3.0%20~%201.3.99-4B8BBE" alt="MaiBot"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="License"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/stargazers"><img src="https://img.shields.io/github/stars/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Stars"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/issues"><img src="https://img.shields.io/github/issues/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Issues"></a>
</p>

<p align="center">
  <a href="#核心特性">核心特性</a> ·
  <a href="#工作原理">工作原理</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#配置">配置</a> ·
  <a href="#flandora-侧配置">Flandora 侧配置</a> ·
  <a href="#支持的消息段">支持的消息段</a> ·
  <a href="#使用边界与许可">使用边界与许可</a>
</p>

本插件是 MaiBot 的消息网关适配器：以正向 WebSocket 客户端身份连上 Flandora 的 OneBot v11 服务端，把微信事件翻译成麦麦的会话消息，再把麦麦的回复翻译成 OneBot 动作请求发回微信。它在整条链路里的位置与 AstrBot 的 `aiocqhttp` 适配器相同——都是主动连过去的一方。

> [!CAUTION]
> 本插件不直接操作微信客户端，收发都由 [Flandora](https://github.com/OMSociety/Flandora) 完成。以自动化方式驱动自己的微信客户端存在账号被限制或封禁的风险，请只用自己的号并自行承担后果；本项目按「现状」提供，与腾讯 / 微信无隶属或授权关系。详见[使用边界与许可](#使用边界与许可)。

## 核心特性

| 特性 | 说明 |
| --- | --- |
| **双向消息** | 群聊与私聊的文本、@、图片、语音、文件按两侧组件模型互相转换，微信里的引用在麦麦里是一条引用段 |
| **引用即 @** | 微信里引用机器人自己发出的消息时，这条消息按被 @ 处理，回复概率拉满，不受回复调度的频率门控影响；开关可关 |
| **通知入流** | 撤回与拍一拍作为通知消息进入麦麦，人名按 ID 现查，被拍的是机器人时写成「张三 拍了拍 你」 |
| **连接自愈** | 指数退避重连、心跳空闲看护、动作超时与失败回执；连接建立时自动把机器人账号上报给麦麦 |
| **消息号回填** | 发出后把微信侧的 `message_id` 通过 `message_id_echo` 回填给宿主，引用与撤回都对得上同一条消息 |

## 工作原理

Flandora 把微信个人号暴露成一个 OneBot v11 服务端；本插件作为 WebSocket 客户端连上去，双向翻译事件与动作。

| 角色 | 职责 |
| --- | --- |
| Flandora | 读微信本地库收消息、走 Windows UI 自动化发消息、维护 wxid 与整数 ID 的映射 |
| 本插件 | 事件与消息段的双向翻译、连接维护、账号上报 |
| MaiBot | 会话管理、上下文与人格、决定回不回以及回什么 |

```
微信 ←→ Flandora ←─ WebSocket（OneBot v11）─→ 本插件 ←→ MaiBot
```

## 快速开始

| 前置 | 要求 |
| --- | --- |
| MaiBot | 1.3.0 – 1.3.99 |
| 插件 SDK | 2.7.0 – 2.99.99 |
| Python | 3.12 及以上（随麦麦运行环境，无需另装） |
| 依赖 | `websockets >= 12.0`（宿主按 `_manifest.json` 自动安装） |
| Flandora | 当前版本，`ob_message_format` 保持默认的 `array` |

1. 把仓库目录（或发布包）放到麦麦的插件目录下，目录名用 `flandora-adapter`。

   ```
   <麦麦目录>/plugins/flandora-adapter/
   ```

2. 在麦麦面板的插件页重载插件，列表里出现「Flandora 微信适配器」。
3. 打开插件配置，把 `[client]` 的 `server` / `port` / `token` 与 Flandora 面板的 `ob_server_host` / `ob_server_port` / `ob_server_token` 对齐。
4. 启动 Flandora 并登录微信。连接建立后日志出现 `消息网关已激活路由：platform=wechat account_id=... scope=flandora`，即接入完成。

最小配置：

```toml
[plugin]
enabled = true
config_version = "1.0.0"

[client]
server = "127.0.0.1"
port = 7999
token = ""
```

> **提示**：`ob_message_format` 请保持默认的 `array`，本插件的段编解码按 `array` 实现。

## 配置

配置分五节，全部带默认值，通常只需要改 `[client]`。

### `[plugin]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 插件总开关；设为 `false` 时插件只登记组件并保持静默，改回 `true` 后重新连接 |
| `config_version` | `str` | `1.0.0` | 配置结构版本，由插件维护；与本插件要求的版本不一致时拒绝启动连接 |

### `[client]`

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

### `[filters]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ignore_self_message` | `bool` | `true` | 挡掉自己在微信客户端手发的消息，避免麦麦自问自答 |
| `ban_user_id` | `list` | 空 | 用户黑名单，命中即不入站；可填整数 ID 或 wxid |
| `ban_group_id` | `list` | 空 | 群黑名单，命中即不入站；可填整数 ID 或群 wxid（`xxx@chatroom`） |
| `quote_wakes` | `bool` | `true` | 引用必回复：引用机器人自己发出的消息时按被 @ 处理；关闭后只按真实的 @ 与提及判断 |

### `[notice]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable_group_recall` | `bool` | `true` | 群成员撤回消息时上报一条通知，内容不含原文 |
| `enable_friend_recall` | `bool` | `true` | 好友撤回私聊消息时上报一条通知，内容不含原文 |
| `enable_poke` | `bool` | `true` | 有人拍一拍时上报一条通知 |

通知文本里的人名由适配器按 ID 现查（群内走 `get_group_member_info`，好友走 `get_stranger_info`），单次查询超过 3 秒或 Flandora 回 `1406` 时回退成数字 ID。撤回通知带 `[事件-xxx]` 前缀；拍一拍按微信原句输出。

### `[debug]`

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `log_raw_events` | `bool` | `false` | 把 Flandora 推送的原始事件写进日志（超长截断），排查协议结构时开启 |

完整模板：

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

## Flandora 侧配置

本插件连的是 Flandora 的 OneBot v11 **服务端入口**（`type = "ws_server"`），地址取插件配置里的 `server` / `port` / `token`。在 Flandora 控制台（默认 `http://127.0.0.1:4950`）把三项对上即可：

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

若 `ob_networks` 里已经写了自定义入口，就在其中保留一个 `type = "ws_server"` 的入口：`port` 必填，`host` 不填按 `127.0.0.1`，`role` 建议 `universal`（`api` 只处理动作请求、`event` 只推事件），`path` 不填即 `/` 且要与插件的连接地址一致。

收件方向还依赖 Flandora 能读到微信本地库。若它的日志里反复出现 `本地库收件源启动失败：找不到微信口令文件 ...\data\wx_key.dat`，说明取钥还没做：连接能建立、发消息正常，微信里的消息要等走完控制台的「取钥向导」才会进来。

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
| `reply` | 以引用段传入，携带被引消息的 `message_id`；被引的是机器人自己发的消息时（事件上的 `reply_to_self`）按被 @ 处理，正文不改写 |
| `video`、合并转发、其它 | 转成占位文本，其余段照常送达 |

**出站（麦麦 → 微信）**

| 麦麦段 | 处理方式 |
| --- | --- |
| `text` | 原文发送（微信侧逐字投递并回读校验） |
| `at` | 数字 ID 发真 @；其它形态记入失败详情 |
| `image` / `emoji` | 内联字节直接发送；本机路径按文件名到 Flandora 的附件目录里取件 |
| `voice` | 以语音文件发送 |
| `file` | 内联字节或本机路径直接发送 |
| `合并转发` | 展开为 `[合并转发]` 段落文本后发送 |

出站目标（群或私聊）取自宿主下发的目标信息，必须是 Flandora 分配过的整数 ID；目标号缺失时这条消息直接失败，错误信息里给出原因。

## 使用边界与许可

> **提示**：本项目以 [AGPL-3.0-or-later](LICENSE) 发布，可以自由使用、修改与再分发，保留版权与许可声明即可。禁止用于任何违法违规用途。

本插件只做消息编解码与连接维护，不触碰微信客户端；消息能否收发取决于 Flandora 与微信本身。以自动化方式驱动你自己的微信客户端可能与微信的用户协议冲突，请只用自己的号，并自行承担账号被限制或封禁的风险。项目为独立工具，与腾讯公司无任何关联，不承诺可用性与送达率；微信改版导致接口失效属官方行为，不在担保范围内。使用产生的一切后果由使用者自行承担。

## 鸣谢与致谢

- [Flandora](https://github.com/OMSociety/Flandora)：把微信个人号接成 OneBot v11 服务端，本插件对接的另一半
- [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)：同为麦麦适配器，插件骨架、配置写法与消息段编解码多有参考
- [OneBot v11](https://github.com/botuniverse/onebot-11)：事件与动作遵循的协议规范
