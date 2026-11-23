<p align="center">
  <img src="https://raw.githubusercontent.com/OMSociety/MaiBot-Flandora-Adapter/main/assets/icon.svg" width="96" alt="Flandora 微信适配器" />
</p>

<h1 align="center">Flandora 微信适配器</h1>

<p align="center">MaiBot 微信个人号适配器插件，支持 Flandora 客户端</p>

<p align="center">
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/releases"><img src="https://img.shields.io/github/v/tag/OMSociety/MaiBot-Flandora-Adapter?label=version&color=07C160" alt="Version"></a>
  <a href="https://github.com/OMSociety/MaiBot"><img src="https://img.shields.io/badge/MaiBot-1.3.19%20~%201.3.99-4B8BBE" alt="MaiBot"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="License"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/stargazers"><img src="https://img.shields.io/github/stars/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Stars"></a>
  <a href="https://github.com/OMSociety/MaiBot-Flandora-Adapter/issues"><img src="https://img.shields.io/github/issues/OMSociety/MaiBot-Flandora-Adapter?color=07C160" alt="Issues"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#flandora-侧配置">Flandora 侧配置</a> ·
  <a href="#文档">文档</a> ·
  <a href="#鸣谢与致谢">鸣谢与致谢</a>
</p>

本插件是 MaiBot 的消息网关适配器：以正向 WebSocket 客户端身份连上 Flandora 的 OneBot v11 服务端，把微信事件翻译成麦麦的会话消息，再把麦麦的回复翻译成 OneBot 动作请求发回微信。

## 快速开始

| 前置 | 要求 |
| --- | --- |
| MaiBot | 1.3.19 – 1.3.99 |
| 插件 SDK | 2.19.0 – 2.21.99 |
| Python | 3.12 及以上（随麦麦运行环境，无需另装） |
| 依赖 | `websockets >= 12.0`（宿主按 `_manifest.json` 自动安装） |
| Flandora | 1.2.0 及以上（入站语音、文件、视频与卡片需要），`ob_message_format` 保持默认的 `array` |

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
| `web_public_host` | 空 | 适配器与 Flandora 不在同一台机器时填 Flandora 这台机器可被访问的主机名或 IP；留空按绑定地址推断，回环绑定回落 `127.0.0.1` |
| `web_bind_host` | `127.0.0.1` | 跨机部署时改成 `0.0.0.0`，否则面板的附件下载端口只有本机可达 |

## 文件收发与配置页

| 方向 | 行为 |
| --- | --- |
| 出站文件（麦麦 → 微信） | 宿主 1.3.16 起把 `file` 段换成短时有效的 http 下载地址；适配器下载到系统临时目录，再以本地路径交给 Flandora。单文件上限 50 MiB；下载失败只丢该文件段，原因写进发送回执，其余内容照常送达。发送返回后立即删除临时文件，超时或结果不明时延迟 10 分钟清理 |
| 入站文件（微信 → 麦麦） | Flandora 已把文件落到本机时随消息带本地路径，适配器读盘后以文件组件交给麦麦；本体不在本机（对方未下载）时只有 `[文件] 文件名（大小）` 文本。分处两台机器时按段里的 http 地址取到本机临时文件 |
| 入站语音与视频（微信 → 麦麦） | 语音按语音组件传入；视频本体在本机时按文件组件传入（正文为 `[视频]`），否则只有 `[视频]` 文本。分处两台机器时按段里的 http 地址取件 |
| 入站卡片（微信 → 麦麦） | 公众号文章、B 站分享、小程序、聊天记录等由 Flandora 展开成可读文本；结构化字段放在 `additional_config.flandora_card` |

跨机取件的单件上限是配置项 `attachment_max_mb`，超时 30 秒，取不到的段退化为占位文本，其余段照常送达；取到的临时文件在消息编码完成后立即删除。内联的 `base64://` 载荷不会以文本形态进日志或兜底文本，长串在日志里折叠成 `base64://<N 字符已省略>`。

插件设置页会显示微信连接状态，并提供「重新连接」按钮；热重载不会把适配器短暂上报成离线。

## 文档

| 想看什么 | 去哪 |
| --- | --- |
| 每个配置项的类型、默认值与说明，以及可直接抄的模板 | [docs/config.md](docs/config.md) |
| 入站与出站两侧的消息段怎么对应、出站目标怎么定 | [docs/segments.md](docs/segments.md) |
| 许可与使用边界 | [docs/boundaries.md](docs/boundaries.md) |
| 工程约定与验收口径 | [AGENTS.md](AGENTS.md) |

## 鸣谢与致谢

- [Flandora](https://github.com/OMSociety/Flandora)：面向微信 PC 客户端的 Windows 桥接程序，把微信个人号接成 OneBot v11 服务端
- [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)：麦麦 QQ 个人号适配器，插件骨架、配置写法与消息段编解码多有参考
- [OneBot v11](https://github.com/botuniverse/onebot-11)：事件与动作遵循的协议规范
