<p align="center">
  <img src="https://raw.githubusercontent.com/OMSociety/MaiBot-Flandora-Adapter/main/assets/icon.svg" width="96" alt="Flandora 微信适配器" />
</p>

<h1 align="center">Flandora 微信适配器</h1>

<p align="center">MaiBot 微信个人号适配器插件，支持 Flandora 客户端</p>

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

本插件是 MaiBot 的消息网关适配器：以正向 WebSocket 客户端身份连上 Flandora 的 OneBot v11 服务端，把微信事件翻译成麦麦的会话消息，再把麦麦的回复翻译成 OneBot 动作请求发回微信。

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

2. 打开插件配置，把 `[client]` 的 `server` / `port` / `token` 与 Flandora 面板的 `ob_server_host` / `ob_server_port` / `ob_server_token` 对齐，配置项全表见[配置说明](docs/config.md)。
3. 启动 Flandora 并登录微信。连接建立后日志出现 `消息网关已激活路由：platform=wechat account_id=... scope=flandora`，即接入完成。

## Flandora 侧配置

本插件连的是 Flandora 的 OneBot v11 **WS 服务端**（`type = "ws_server"`），地址取插件配置里的 `server` / `port` / `token`。在 Flandora 控制台把三项对上即可：

| Flandora 配置项 | 默认值 | 与本插件的关系 |
| --- | --- | --- |
| `ob_server_host` | `127.0.0.1` | 对应插件的 `server`；同机部署保持回环 |
| `ob_server_port` | `7999` | 对应插件的 `port` |
| `ob_server_token` | 空 | 对应插件的 `token`；两边要么都留空，要么填同一串字符 |
| `ob_message_format` | `array` | 保持默认，本插件的段编解码按 `array` 实现 |
| `ob_networks` | 空 | 留空即可 |

## 文档

| 想看什么 | 去哪 |
| --- | --- |
| 每个配置项的类型、默认值与说明，以及可直接抄的模板 | [docs/config.md](docs/config.md) |
| 入站与出站两侧的消息段怎么对应、出站目标怎么定 | [docs/segments.md](docs/segments.md) |
| 许可与使用边界 | [docs/boundaries.md](docs/boundaries.md) |
| 工程约定与验收口径 | [AGENTS.md](AGENTS.md) |

## 鸣谢与致谢

- [Flandora](https://github.com/OMSociety/Flandora)：面向微信 PC 客户端的 Windows 桥接程序,把微信个人号接成 OneBot v11 服务端
- [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)：麦麦 QQ 个人号适配器，插件骨架、配置写法与消息段编解码多有参考
- [OneBot v11](https://github.com/botuniverse/onebot-11)：事件与动作遵循的协议规范
