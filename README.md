<p align="center">
  <img src="https://raw.githubusercontent.com/OMSociety/MaiBot-Flandora-Adapter/main/assets/icon.svg" width="96" alt="Flandora 微信适配器" />
</p>

<h1 align="center">Flandora 微信适配器</h1>

<p align="center">把 Flandora 桥接的微信个人号接进 MaiBot：群聊与私聊的收发、引用、撤回与拍一拍都在麦麦里看得见。</p>

<p align="center">
  <a href="https://github.com/OMSociety/MaiBot"><img src="https://img.shields.io/badge/MaiBot-1.3.0%20~%201.3.99-4B8BBE" alt="MaiBot"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="License"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/stargazers"><img src="https://img.shields.io/github/stars/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Stars"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/issues"><img src="https://img.shields.io/github/issues/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Issues"></a>
</p>

<p align="center">
  <a href="#核心特性">核心特性</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#flandora-侧配置">Flandora 侧配置</a> ·
  <a href="#文档">文档</a> ·
  <a href="#鸣谢与致谢">鸣谢与致谢</a>
</p>

本插件是 MaiBot 的消息网关适配器：以正向 WebSocket 客户端身份连上 Flandora 的 OneBot v11 服务端，把微信事件翻译成麦麦的会话消息，再把麦麦的回复翻译成 OneBot 动作请求发回微信。它在整条链路里的位置与 AstrBot 的 `aiocqhttp` 适配器相同——都是主动连过去的一方。

## 核心特性

| 特性 | 说明 |
| --- | --- |
| **双向消息** | 群聊与私聊的文本、@、图片、语音、文件按两侧组件模型互相转换，微信里的引用在麦麦里是一条引用段 |
| **引用即 @** | 微信里引用机器人自己发出的消息时，这条消息按被 @ 处理，回复概率拉满，不受回复调度的频率门控影响；开关可关 |
| **通知入流** | 撤回与拍一拍作为通知消息进入麦麦，人名按 ID 现查，被拍的是机器人时写成「张三 拍了拍 你」 |
| **连接自愈** | 指数退避重连、心跳空闲看护、动作超时与失败回执；连接建立时自动把机器人账号上报给麦麦 |
| **消息号回填** | 发出后把微信侧的 `message_id` 通过 `message_id_echo` 回填给宿主，引用与撤回都对得上同一条消息 |

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
3. 打开插件配置，把 `[client]` 的 `server` / `port` / `token` 与 Flandora 面板的 `ob_server_host` / `ob_server_port` / `ob_server_token` 对齐，配置项全表见[配置说明](docs/config.md)。
4. 启动 Flandora 并登录微信。连接建立后日志出现 `消息网关已激活路由：platform=wechat account_id=... scope=flandora`，即接入完成。

> **提示**：`ob_message_format` 请保持默认的 `array`，本插件的段编解码按 `array` 实现。

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

## 文档

| 想看什么 | 去哪 |
| --- | --- |
| 每个配置项的类型、默认值与说明，以及可直接抄的模板 | [docs/config.md](docs/config.md) |
| 入站与出站两侧的消息段怎么对应、出站目标怎么定 | [docs/segments.md](docs/segments.md) |
| 许可与使用边界 | [docs/boundaries.md](docs/boundaries.md) |
| 工程约定与验收口径（给改代码的人） | [AGENTS.md](AGENTS.md) |

## 鸣谢与致谢

- [Flandora](https://github.com/OMSociety/Flandora)：把微信个人号接成 OneBot v11 服务端，本插件对接的另一半
- [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)：同为麦麦适配器，插件骨架、配置写法与消息段编解码多有参考
- [OneBot v11](https://github.com/botuniverse/onebot-11)：事件与动作遵循的协议规范
