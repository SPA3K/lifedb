# Life Timeline DB — 个人多模态时间线数据库

> 孙哥命题："任何无法被AI记录的事情都不该做"。
> 目标：把散落在 Obsidian / OneDrive / 训记 / Google Maps / 一生轨迹 / 未来 Look 的个人数据，
> 以 **timestamp 为唯一主索引** 归纳进一个本地个人 DB，让 AI（Hermes/LifeOS）可查询、可关联。

## 0. 设计原则（不重复造轮子）

1. **一个 SQLite 文件就是全部基础设施** — 零服务、零账号、单文件可备份可迁移。
   位置：`~/.hermes/life-db/timeline.db`
2. **Obsidian 不替代、只增强** — vault 继续做人类主 UI 和内容载体；
   DB 只存**元数据 + 指针**（文件路径、时间、geo、tags），不复制正文 → 无双写漂移。
3. **时间戳是唯一跨模态 join key** — 所有事件归一为统一 schema，
   "2026-07-15 那天发生了什么" 一条 SQL 出全部模态。
4. **写入层幂等** — 每条事件有 content_hash，重跑导入不产生重复。
5. **LifeOS 是消费方不是存储方** — DB 通过 Hermes skill 暴露查询，
   LifeOS MEMORY/ATLAS 引用 DB 而非另建一份。

## 1. 统一事件 schema（核心）

```sql
CREATE TABLE event (
  id          INTEGER PRIMARY KEY,
  ts_start    TEXT NOT NULL,        -- ISO8601 UTC, 必填, 主排序键
  ts_end      TEXT,                 -- 区间事件(旅行/会议/训练)才有
  modality    TEXT NOT NULL,        -- note|photo|workout|location|video|podcast|finance|health|...
  source      TEXT NOT NULL,        -- obsidian|onedrive|xunjii|gmaps|lifetrack|look|...
  title       TEXT,                 -- 人类可读摘要
  summary     TEXT,                 -- AI生成的一句话(可空,惰性填充)
  payload_ref TEXT,                 -- 指针: 文件路径/URL/原记录ID
  payload_hash TEXT,                -- 去重键
  lat REAL, lon REAL,               -- geo(可空)
  tags        TEXT,                 -- JSON array
  meta        TEXT                  -- JSON: 模态特有字段(卡路里/步数/相册名/笔记frontmatter...)
);
CREATE INDEX idx_event_ts   ON event(ts_start);
CREATE INDEX idx_event_mod  ON event(modality, ts_start);
CREATE INDEX idx_event_geo  ON event(lat, lon);
CREATE UNIQUE INDEX idx_event_dedup ON event(source, payload_hash);
```

要点：
- `ts_start` 是唯一必填的时间字段，**没有时间的信息不进 DB**（降级为"待归档"桶）。
- geo 三列独立索引 → 支持"去年夏天在杭州的照片+轨迹+笔记"这类空间-时间联合查询。
- `meta` JSON 承载模态差异，不为每种模态建表（SQLite JSON1 函数可查询）。

## 2. 数据源清单与接入方式

| 源 | 模态 | 导出路径 | 接入难度 | 状态 |
|---|---|---|---|---|
| Obsidian vault | note | 直接读 .md + frontmatter + mtime | ⭐ 最低 | **缺 vault 路径** |
| OneDrive 照片 | photo | EXIF DateTimeOriginal | ⭐⭐ | **缺同步目录** |
| 训记 | workout | App 内导出 CSV / 邮件申请 | ⭐⭐ | 待你导出 |
| Google Maps Timeline | location | 手机设置→时间线→导出 JSON | ⭐⭐⭐ | ⚠️ 2024.12后本地存储,需手机端导出 |
| 一生轨迹 | location | GPX/KML 导出 | ⭐⭐ | 待确认导出口 |
| 小宇宙播客数据 | podcast | 已有 API 采集 | ⭐ | ✅ 已有脚本可复用 |
| 周报/work文件 | note | 同 Obsidian | ⭐ | 同 vault |
| Look 记录仪 | video | (未来) | ⭐⭐⭐⭐ | 没买,schema 预留 video 模态 |

每个源一个 **adapter 脚本**（Python），模式统一：
`fetch → 归一化为 event dict → hash去重 → upsert into SQLite`。

## 3. 查询层（给 AI 用的三个入口）

- `life-db query "2026-07"` → 该月全部事件时间线
- `life-db around 2026-07-15T15:00 --window 2h` → 某时刻±2h 的跨模态事件
  （回答"我那天下午在哪、练了什么、拍了什么、写了什么"）
- `life-db correlate photo location --month 2026-07` → 模态关联分析

实现：一个 CLI（`life-db`）包 sqlite3 查询，Hermes 通过 terminal 直接调用。
未来在 Obsidian 侧用 Dataview/生成式 MD 把日聚合写回 vault 供人类浏览。

## 4. 与 LifeOS 的关系

- LifeOS MEMORY/ATLAS 继续管"认知层"（目标、复盘、身份），
  LifeDB 管"事实层"（原始事件流）。
- 复盘类工作流（周回顾）= LifeOS 拉 LifeDB 当周事件 → 生成总结 → 写回 Obsidian vault。
- Hermes skill `life-db` 封装 CLI，让 agent 在任何会话里可查。

## 5. 分期落地

- **P0（今天可做）**：schema + CLI + obsidian/photos 两个 adapter（等你给路径）
- **P1**：训记 CSV + Maps Timeline JSON adapter；日聚合写回 vault
- **P2**：Hermes skill + LifeOS MEMORY 挂接；周报自动生成
- **P3**：Look/视频模态、语义检索(向量化 summary)

## 6. 隐私边界

全本地，不上传。SQLite 单文件 = 加密可选（SQLCipher）。
AI 只通过 CLI 查询，不持有原始照片/视频。
