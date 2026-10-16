# LifeDB 产品定义（v2）

> 2026-10-16 · 状态：Approved（用户拍板）
> 本文取代 PRD v1 的"定位/架构/路线"部分；PRD（`PRD-lifedb-visual-app.md`）保留功能规格与验收标准。
> 变更核心：**从"自用工具"转向"开源产品"** —— 我们做内核 + 本机 MCP 服务 + 少量 show demo；
> 应用层生态交给开源开发者，他们只需接入我们的 MCP。

---

## 1. 定位

**一句话**：local-first 的个人多模态时间线数据库。你的位置、照片、训练、睡眠、笔记，
归一到一张 SQLite；零上传、零遥测、数据不出本机。

**生态位**（与 PRD v1 相同，产品化后更强）：
- Google Timeline 砍掉桌面网页版后，"个人轨迹主权"出现空缺 → 我们接住
- 没有任何项目把"轨迹 + 照片 + 训练 + 健康 + 笔记"放在同一时间轴上 → 这是独占数据结构
- 隐私即卖点：所有能力都在本机运行，MCP 服务只监听 localhost

## 2. 架构（三层）

```
┌────────────────────────────────────────────────┐
│  App 层（应用生态）                              │
│  我们只出 demo：                                 │
│    demo/atlas      Life Atlas 交互地图 (F1/F3)  │
│    demo/wrapped    年度/周分享卡 (F4/F9)         │
│    demo/traincoach 训练日视图 (F6)               │
│  其他开发者 → 用任何语言接 MCP 自建应用           │
├────────────────────────────────────────────────┤
│  MCP 服务（本机, stdio / 127.0.0.1）             │
│  mcp_server.py — 内核能力的唯一对外契约           │
│  工具面见 §4；不含任意 SQL，读为主 + 受控写入     │
├────────────────────────────────────────────────┤
│  Kernel 层（内核）                               │
│  timeline.db (SQLite) · schema.sql              │
│  event 表（统一事件）+ geo_point 表（秒级 GPS）   │
│  统一导入层：JSONL 事件契约 + adapter manifest    │
│  CLI: life-db init/ingest/query/around/stats     │
└────────────────────────────────────────────────┘
```

**设计原则**
1. **内核不知道应用**。内核只保证：schema 稳定、导入幂等、查询走索引。
2. **MCP 是契约**。应用层（包括我们自己的 demo）只通过 MCP 工具面读数据；
   改契约 = 大版本，工具只增不改不删。
3. **导入层不做死**。我们只维护"统一导入接口"（JSONL 事件契约 + adapter manifest 规范），
   具体 app 的 adapter 是插件，欢迎社区 PR（模板见 §3）。

## 3. 统一导入层

### 3.1 接口契约（两个文件即插件）

- **事件契约**：每行一个 JSON，字段 `ts_start | modality | source` 必填，
  `ts_end | title | summary | lat | lon | tags | meta | payload_ref` 可选。
  `payload_hash = sha256(source|payload_ref|ts_start)[:16]` 保证幂等（重复导入零副作用）。
- **adapter manifest**：`adapters/<name>.manifest.json`，字段：
  `name / implements / modality / source / entry / cmd / mode / incremental /
  dry_run / status / notes / secrets_env`。
  manifest 即文档：`life-db adapters` 直接列出全生态支持面。

### 3.2 已支持的数据源（现状）

| adapter | 数据源 | 模态 | 模式 | 幂等机制 | 状态 |
|---|---|---|---|---|---|
| `lifetrack` | 手机 GPS 轨迹（秒级） | geo_point | periodic | 时间戳 upsert | ✅ active |
| `xunji` | 训记 App（力量训练） | workout | periodic | payload_hash=xj-\<localid\> | ✅ active |
| `apple_health` | Apple 健康导出 zip | sleep / workout / workout_route / ecg / health_metric / health_event | manual | sha1 段指纹 | ✅ active |
| `gmaps` | Google Timeline 导出 | stay / segment | manual | 坐标+时间窗 hash | ✅ active |
| `photo` | 照片目录 EXIF | photo | manual | 文件 sha1 | ✅ active |
| `geolocate` | 坐标→地名反查 | enrich | on-demand | — | ✅ active |
| iCloud sync 工具链 | 照片/健康包自动下载 | （供上面 adapter 消费） | periodic | — | ✅ active |

### 3.3 规划中（欢迎社区认领，good-first-issue 级别）

| 数据源 | 说明 | 优先级 |
|---|---|---|
| **Hevy / Strong / Strava CSV 导出** | 力量训练国际主流源，workout 模态 | P1 |
| **GPX / FIT 文件** | 通用运动轨迹，任何人手表都能导 | P1 |
| **Google Takeout Location History（新版 Records.json）** | 海外用户最大存量轨迹 | P1 |
| **Obsidian / 通用 Markdown vault** | 笔记模态（PRD F8） | P2 |
| **Keep / 小米运动 / 华为运动健康** | 国内健身/健康数据 | P2 |
| **Garmin Connect 导出** | 健康+运动 | P2 |
| **Bilibili / 网易云播放记录** | 数字生活模态 | P3 |

> 新增 adapter 的验收标准（PR 模板）：① manifest 完整 ② `--dry-run` 可用 ③
> 重复导入零副作用（附测试样例 jsonl）④ secrets 只走 env/本地 conf，绝不入库。

## 4. MCP 服务契约（v0.1）

入口：`py -3 mcp_server.py`（stdio）。数据库路径：`LIFEDB_DB` 环境变量，
默认 `~/.hermes/life-db/timeline.db`（TODO：迁移到 XDG 配置，见路线图 C）。

| 工具 | 入参 | 返回 | 用途 |
|---|---|---|---|
| `lifedb_stats` | — | schema 版本 / 各模态计数 / 时间覆盖 | 应用启动自检 |
| `lifedb_query_month` | `month`, `limit`, `offset` | 该月事件流（统一 schema 行） | 时间轴浏览 |
| `lifedb_around` | `ts`, `window`(如 `2h`), `limit` | 跨模态事件窗（三分支 UNION，全索引 seek） | "那一刻发生了什么" |
| `lifedb_geo_track` | `start`, `end`, `limit` | 原始 GPS 点序列 `[ts,lat,lon,alt,speed]` | 轨迹渲染（deck.gl/Manim 喂这个） |
| `lifedb_export_atlas` | `start`, `end`, `modalities?`, `max_points` | `{track, events, photos}` 打包 JSON | 地图类应用的一站式数据源 |
| `lifedb_ingest_jsonl` | `path`, `dry_run`(默认 true) | 导入/去重计数 | 数据回灌（唯一写入口） |
| `lifedb_adapters` | — | 全部 adapter manifest | 生态发现 |

**安全边界**：不暴露任意 SQL；`lifedb_ingest_jsonl` 默认 dry-run；
所有工具只操作本机 DB 文件。这三条写进 README 的隐私声明。

## 5. 路线图 v2

- **Phase A · 开仓准备**（本周）
  - [x] 私有数据黑名单（.gitignore：DB/凭据/缓存/个人产出）
  - [x] LICENSE(MIT) + README(中英) 骨架 + PRODUCT.md
  - [x] git init + 提交（mp4/gif/png 等内嵌个人轨迹的生成物永不入库；README 展示用
        素材经 docs/assets/ 显式入库，用户已确认公开）
  - [x] 路径去硬编码（LIFEDB_DB/LIFEDB_HOME 环境变量覆盖, 包内相对路径）
  - [ ] manifest notes 里的个人化表述清洗（如"已入库 125 训练日"）
- **Phase B · MCP v0.1**（本周）
  - [x] lifedb/mcp.py 七个工具（stdio）· 契约见 §4
  - [x] 本地 client 握手验证（tests/smoke_mcp.py，7 工具全绿）
  - [x] Claude Desktop / Claude Code 接入示例写进 README
  - [x] mcp 1.x / 2.x 双版本兼容（2.x FastMCP→MCPServer 改名自动回退）
  - [ ] Windows/macOS/Linux 三平台接入实测
- **Phase C · Demo 层**（1–2 周）
  - [x] `demo/movie`：人生电影 —— 一键 mp4（hero demo，非交互、README 自动播放、
        竖版副产物发社媒；传播优先于交互，2026-10-16 用户拍板）
  - [x] `demo/wrapped`：年度/周分享卡流水线收编（数据层+渲染层，out/ 不入库）
  - [ ] `demo/traincoach`：训练日视图（PRD F6）
  - [x] 打包：pyproject + `pip install -e .` 验证（console scripts:
        `life-db` / `lifedb-mcp`；PyPI 发布待 org 名确定）
  - [ ] （可选，非 hero）`demo/atlas`：交互式地图单文件 HTML（PRD F1 降级为可选项）
  - [x] README（marketing 结构：引言→痛点→BYO Agent/BYO Data→showcase→快速开始）
- **Phase D · 社区开放**
  - [ ] CONTRIBUTING.md + adapter 模板 + good-first-issue 清单（§3.3 即种子）
  - [ ] CI（lint + adapter 幂等性测试 + golden-file）
  - [ ] docs 站（安装/数据源/隐私声明/ MCP API 参考）

**明确不做**：SaaS、账号体系、云端部署、遥测。产品的承诺就是这些的反面。

## 6. 开放问题

1. 包名/品牌名沿用 `life-db` 还是另取？（GitHub org 名待定）
2. MCP 除 stdio 外是否提供 `127.0.0.1:8787` 的 streamable-http（多应用共享一个内核实例）？
   —— v0.2 再议，stdio 先行（Claude Desktop 原生支持）
3. README 首发语言：建议中英双语（README.md + README.zh-CN.md）
