# Changelog

本项目的更改记录在此文件。

All notable changes to this project are documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-02

### 新增

- 支持出站文件：宿主下发的 http 签名地址会先下载到系统临时目录，再以本地路径交给
  Flandora；单个文件上限 50 MiB，下载失败只丢该文件段，原因写进发送回执
  `metadata.dropped_segments`，其余内容照常送达。
- 插件设置页新增「微信连接器状态」与「重新连接」两个控件；重连会静默断开旧连接再重建。

### 变更

- 最低支持版本提升到 MaiBot 1.3.19、插件 SDK 2.19.0，移除面向旧版本的兼容分支。
- `on_unload` 接受 `for_reload`：热重载时静默断开，不再把重载上报成离线。

### 说明

- 入站文件仍只上报 `[文件] 文件名` 占位文本：微信文件本体在 CDN 上，Flandora 拿不到，
  见 [docs/wip.md](docs/wip.md)。

