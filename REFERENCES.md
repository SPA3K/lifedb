# 大记理论 — 外部参考系统

发现渠道：用户 2026-10-13 提供。已克隆到 `references/`（ghfast.top 镜像），均非代码依赖，**只借鉴架构与 schema 设计**。

## 1. avsm/lifedb-server（Anil Madhavapeddy，OCaml，2009，⭐2）

> 本地：`references/lifedb-server/` · 个人数据管理服务器，技术栈老（OCaml 3.11/Camlp4/autoconf），**代码不可直接复用，架构思想可抄**。

### 值得借鉴的机制

| 机制 | 原文设计 | 对大记理论的启发 |
|---|---|---|
| **插件清单** | 插件目录放 `LIFEDB_PLUGIN` JSON：`{name, cmd, declares:[{pltype, implements: "public.message"}]}` | 我们的 `adapters/` 可加同名清单文件（声明 modality + 增量策略 + 依赖），CLI 自动发现 |
| **任务配置 .conf** | `mode: periodic/constant/single` + `period` 秒 + `silo`（数据子目录）+ `args`（如 FULL_SYNC 开关） | 增量任务的标准化描述：训记=periodic(每日)、Google Timeline=periodic、一生轨迹=single。替代 skill 里手写的"下一步" |
| **secret 注入** | task.conf 的 `secret:{service,username}` → 从 DB 查出 → 以 `LIFEDB_USERNAME/LIFEDB_PASSWORD` 环境变量传给脚本 | 比现在 `~/.hermes/life-db/keys.json` 更工程化；后续可把各 API key 收进 keychain（Windows 用 Credential Manager） |
| **`-test` dry-run** | 不真跑外部命令，其余全走一遍 | 所有 adapter 必带 `--dry-run`（拉取/入库链路空跑验证） |
| **目录分层** | lifedb_dir / log_dir / cache_dir / config_dir / static_dir 五分 | 我们已是 `~/.hermes/life-db/`（db+keys）与 `adapters/_xunji_cache/`（缓存）二分，够用；日志可补 `logs/` |
| **HTTP 日期查询 API** | `/date/<y>/<m>`（月历+条数）、`/date/<y>/<m>/<d>`（当日列表）、`/doc/<id>`（单条+联系人）、`/q/contact/date/...` | 未来 LifeOS 查询层可直接照抄这套 URL 语义（映射到我们的 timestamp 索引 + event 主键） |
| **schema 三件套** | `keychain_schema` / `sync_schema` / `log_schema` + `schema_generator` | schema 与数据分离、可生成；sync_schema 提示多设备同步是终局需求 |
| **双库** | `life.db`（主缓存）+ `log.db`（任务日志/进度） | 我们未来可在 event 表外加 `ingest_log` 表记录每次 adapter 运行 |

## 2. p-i-c-o/lifedb（2025，⭐0）

> 本地：`references/lifedb/` · self-hosted 医疗/身体信息系统。README 只有 banner，**核心资产是 `template.json`**——单日健康记录的 JSON 模板（`_schema_version: 1`）。

### template.json 字段块（15 块）

`sleep`（起止/质量/打鼾/梦）、`meals[]`（营养素/情绪前后）、`hydration`、`supplements[]`、`medications[]`、`activities[]`（配速/心率/RPE/天气/室内外）、`mental_state`（情绪/能量/专注/压力 9 量表）、`screen_time`、`habits`（冥想/日光/咖啡因…）、`biometrics`（体重/体脂/HRV/BP/血糖/血酮）、`health_events[]`（症状/诱因/缓解）、`productivity`、`environment`、`notes`、`tags`

### 对大记理论的启发

1. **LIFE 表扩容蓝图**：我们目前训练块只有 `sets/volume/times/movements`；这个模板给出健康日志的完整字段清单——未来接 Apple Health / 手环数据时按块映射
2. **`_schema_version` 字段**：我们 schema.sql 目前无版本号，应补（ALTER 迁移需要）
3. **情绪前后对照**（meals.mood_before/after）与**症状链**（health_events.trigger→recovery_method）：因果查询的最小数据结构
4. 与我们 LIFE 表已有块的对应：`训练`≈activities、`消费`≈meals、`创作`≈productivity、`睡眠`≈sleep（我们只有 summary 一句话，可细化）

## 3. browser-use/life-recorder（⭐326，Swift + Python，2026-09 活跃）

> 本地：`references/life-recorder/` · iPhone 原生录音 + Mac 本地接收转写，**四个参考里唯一星最高且活跃的**（browser-use 官方 org 出品）。

**它是什么**：iPhone 每分钟切一段 AAC 录音 → 局域网 HTTPS + 256bit bearer token 上传 → Mac 端 **whisper.cpp 本地转写**（无云、无付费 ASR）→ 汇成**一份连续 `life.md`（带小时标记）**→ 转写成功后删音频。离线队列、断点重传、接收确认后才删。

### 值得借鉴的机制

| 机制 | 原文设计 | 对大记理论的启发 |
|---|---|---|
| **连续生活文档** | 单一 `life.md` + 每小时 `HH:00` 标记，持续追加 | 与我们 timestamp 索引理念同构——可作为 event 表的"人类可读镜像"（周回顾直接读它） |
| **1 分钟切片 + 确认删除** | 音频在接收方 ack + 转写成功后才删；离线排队、stale 任务取消 | 未来接"语音生活记录"模态的传输协议照抄：本地优先、幂等、at-least-once |
| **隐私边界** | LAN HTTPS + 证书固定 + 随机 token，无隧道无云；运行态全在 Git 外 | 我们 keys.json / timeline.db 的"运行态不进仓库"原则一致，可补进 DESIGN |
| **幻觉清洗** | 转写后过滤舞台指示词 + 高频重复幻觉噪声 | 本地 Whisper（我们已有 local-whisper 技能）入库前的必做后处理 |
| **SKILL.md 范式** | 仓库自带 Codex 操作技能（构建/配对/排障全流程 + 权限边界声明） | 与我们 skill 体系同构；大记理论未来接手机端时可直接套这个流程 |
| **iOS 限制注记** | 重启/强退后需手动开一次 app 才能恢复录音 | 真机部署的坑，记下备用 |

## 4. Life-Palette/LifePalette-Web「拾色」（⭐78，React/TS，2026-10 活跃）

> 本地：`references/LifePalette-Web/` · 中文个人记忆产品：照片色彩画廊 + 足迹地图 + 微日记 + AI 续写，**展示层参考**（我们目前纯 CLI，没有 Web 端）。

### 值得借鉴的机制

| 机制 | 原文设计 | 对大记理论的启发 |
|---|---|---|
| **照片提色画廊** | 浏览器端自动提取图片主色调、色轮分布、按色浏览、年度"主色调" | 照片模态（OneDrive 目录待接）入库时可顺带提主色存 meta，未来按色检索/年度回顾 |
| **地图轨迹海报** | Mapbox + 照片自动定位 + 轨迹聚合 + 导出足迹海报 | 我们 294k GPS 点 + 833 停留段的可视化方案——Web 端首选 Mapbox GL |
| **EXIF 前端提取** | 浏览器端读 EXIF 元数据 + Blurhash + Live Photo | 照片 adapter 可先用前端/脚本双路提取 EXIF 时间对齐到 timestamp 轴 |
| **技术栈** | React + TanStack Query/Router/Virtual + Plate.js 富文本 + Socket.io | 未来 LifeDB 查看器的现成栈参考；TanStack Virtual 对 30 万行事件列表是必需品 |
| **AI 续写** | 停止输入 1.5s 自动联想、润色、Ghost Text | 未来"日记类事件"的输入体验参考 |

## 结论

- 四个仓库分两类：**架构参考**（avsm 任务/插件、life-recorder 数据管线）与 **schema/展示参考**（p-i-c-o 健康字段、拾色 Web 端）
- 生态位差异：它们要么是设计稿（⭐0-2），要么是单模态工具（⭐326 只做录音、⭐78 只做照片展示）；**大记理论的差异点 = 多模态统一 timestamp 索引 + agent 原生（CLI/skill 直查）**，目前无同类直接竞品
- 优先级不变：先落 `_schema_version` 和 adapter 清单；life-recorder 的"连续 life.md"与"确认删除协议"排在接入语音模态时用；拾色的 Mapbox 方案留给 LifeOS 周回顾可视化
