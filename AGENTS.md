# AGENTS.md

写给在此仓库上作业的 AI 代理。只写工具管不住、且能判定的规则。

## 项目定位

MaiBot 的消息网关插件：以正向 WebSocket 客户端身份连 Flandora，把微信个人号的消息
送进麦麦，把麦麦的回复送回微信。仓库只有这一个插件，没有第二个产物。

## 验收命令

提交前四条全绿，一条不过不提交：

```
python -m ruff check .
python -m ruff format --check .
python -m pytest tests -q
python -m compileall -q .
```

插件中心离线校验器（`maibot-plugin-creator` 技能内的 `check_plugin.py`）要求 0 error。
`capability-empty` 这条 warn 是本仓库的预期状态，见下面「宿主契约」。

## 依赖方向

自下而上单向，箭头方向可以依赖，反向不行：

```
constants / debug / runtime_state        ← 只用标准库
config                                   → constants（+ maibot_sdk、pydantic）
transport                                → 标准库 + websockets；config 只在 TYPE_CHECKING 下引用
codecs/                                  → constants
services/                                → transport
runtime/                                 → codecs / config / constants / debug / runtime_state / services
plugin.py                                → 以上全部
```

`plugin.py` 位于最上层，其余模块一律不引用它。

## 导入约定

包内一律相对导入（`from .constants import ...`、`from ..transport import ...`）。
仓库根目录不放 `__init__.py`，子包（`codecs/`、`services/`、`runtime/`）各放一个。
这样插件目录名带连字符也能被宿主按目录加载。

## 宿主契约

以下几点取自 MaiBot SDK 源码，改代码时按实况对齐：

- 日志一律走 `self.ctx.logger`。`MaiBotPlugin` 没有 `logger` 属性。
- `_manifest.json` 的 `capabilities` 保持空数组。网关走的是
  `ctx.gateway.route_message` / `update_state`，经 `call_host_method` 直通宿主 RPC，
  不经过能力闸；声明 `host.route_message` 只会换来一条 `capability-unused`。
  新增能力调用时，同步在 manifest 里声明并在 `tests/` 里覆盖到。
- `@MessageGateway` 的 `route_type` 只接受 `send`、`receive`、`duplex`。
- 出站 handler 返回 `{"success": bool, "external_message_id": str | None, "error": str, "metadata": {...}}`；
  成功时 `external_message_id` 取 Flandora 响应里的 `data.message_id`，
  需要回填消息号时附 `adapter_callbacks` 里的 `message_id_echo`。
- 入站 `message_dict` 的必需字段是 `message_id`、`platform`、`message_info`、`raw_message`。
- 修改生命周期、配置热更新或网关 handler 时，`tests/test_plugin_lifecycle.py` 必须覆盖到。

## 配置

- 五个节固定为 `plugin` / `client` / `filters` / `notice` / `debug`，新增字段必须有默认值
  （宿主用默认值构造配置模型，缺默认值会在加载期失败）。
- 改字段名属于破坏性变更：同步 `docs/config.md`、`tests/` 与宿主插件目录里的 `config.toml`，
  并把 `config_version` 一并处理。
- 附件大小对外以 MB 计量（`attachment_max_mb`），字节数由 `attachment_max_bytes` 属性换算。

## 交付面

- README、配置项说明、manifest 描述只写当前状态的客观行为，用陈述句。
- 当前版本做不到的事写进 `docs/wip.md`，按「后续版本计划」组织；README 与配置面板不引用它。
- `CHANGELOG.md` 的标准头部保持双语长式；首个版本只留头部，版本条目自下一个版本起写。
- 版本号变更前先与维护者确认，`pyproject.toml`、`_manifest.json` 与 CHANGELOG 三处同步。
- 提交信息用中文，前缀 `feat:` / `fix:` / `docs:` / `refactor:`，破坏性变更写 `feat!:` / `fix!:`。

## 消息段

- 入站段映射在 `codecs/segments_in.py`，出站段映射在 `codecs/segments_out.py`；
  改任一侧都要同步 `tests/` 与 `docs/segments.md` 的两张段表。
- 未知段类型转成占位文本并记 warning，整条消息照常送达。
- 出站目标必须是 Flandora 分配过的整数 ID，非整数在本地拦下并给出原因。
- 「被提及」有三个来源：段里的 `at` 指向自己、事件上的 `is_mentioned`、事件上的 `reply_to_self`。
  前两者抬 `is_at`；`reply_to_self` 在 `quote_wakes` 开启时也抬 `is_at`（按被 @ 处理，
  宿主的 `inevitable_at_reply` 会因此拉满回复概率），关闭时只抬 `is_mentioned`。
  三者都写进 `additional_config` 供宿主与下游判断；`reply_to_self` 始终是事件里的真实值，
  不与「按 @ 处理」混写。

## 测试

- 测试文件用 `tests/conftest.py` 的 `load()` 取模块（仓库目录名不能当包名导入）。
- 依赖宿主 SDK 的用例用 `pytest.importorskip("maibot_sdk")`，在无 SDK 的环境里跳过。
- 生命周期用例覆盖 `on_load` / `on_config_update` / `on_unload` 与网关 handler 的返回形状；
  只验证构造函数与 `get_components()` 不足以说明插件能在宿主里跑起来。

## 联调

装进宿主时整体同步到宿主插件目录，保留该目录里宿主生成的 `config.toml`
（其中是运行期配置）。宿主不监听插件目录，改动后需要在麦麦面板重载插件或重启宿主。

## 数据

`config.toml`、`data/`、日志目录、`__pycache__` 与各类缓存都在 `.gitignore` 里。
提交内容一律用假 wxid、假群号、假令牌。
