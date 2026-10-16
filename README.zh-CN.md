# LifeDB

> **你的人生，一个 SQLite 文件。** local-first 个人多模态时间线数据库 ——
> 位置、照片、训练、睡眠、笔记，归一到同一时间轴。
> 零上传、零遥测、数据不出本机。

**English** · 中文

*状态：early preview。API 可能变动，尚未发布 PyPI。*

## 为什么

- **Google 砍掉了 Timeline 网页版** —— 几亿人的"年度足迹地图"没了。
  你的位置历史不该活在别人的服务器上。
- **每个 App 只占一个切片**：照片在这、训练在那、GPS 在别处。
  没有任何产品把它们放在**同一根时间轴**上 —— 跨模态视图是我们独占的东西。
- **隐私即产品**：一切在本机运行，包括应用接入用的 MCP 服务。

## 架构

```
应用层   →  你的应用，通过 MCP 接入        （我们只出少量 demo）
MCP 服务 →  mcp_server.py（仅本机）        （唯一对外契约）
内核     →  SQLite + 统一导入层 + CLI
```

应用只通过 **MCP 工具面**访问数据 —— Claude Desktop / Claude Code / 任意
MCP 客户端皆可接入，应用层用什么语言都行。

## 快速开始（preview）

```bash
git clone <this-repo> && cd life-db
life-db init                       # 建库
life-db ingest events.jsonl        # 统一 JSONL 契约，幂等可重放
life-db query 2026-10              # 某月全模态时间线
life-db around 2026-10-13T09:00 --window 2h   # 那一刻前后发生了什么
life-db stats                      # 覆盖度与计数
```

### MCP 接入（Claude Desktop / Claude Code）

```json
{
  "mcpServers": {
    "lifedb": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": { "LIFEDB_DB": "/path/to/timeline.db" }
    }
  }
}
```

工具：`lifedb_stats` · `lifedb_query_month` · `lifedb_around` ·
`lifedb_geo_track` · `lifedb_export_atlas` · `lifedb_ingest_jsonl` ·
`lifedb_adapters`

## 数据源

导入 adapter 是**插件**——一个 manifest + 一个脚本。现已支持：手机 GPS 轨迹、
训记训练、Apple 健康导出、Google Timeline、照片 EXIF、iCloud 同步。

想接你的数据源？见 [docs/PRODUCT.md](docs/PRODUCT.md) §3.3 的路线图
（GPX/FIT、Hevy、Strava、Takeout、Obsidian……）—— 欢迎 PR。

## 隐私

- 无账号、无云端、无遥测。
- MCP 服务只走 stdio / 本机回环。
- 不暴露任意 SQL——读工具全部走索引查询，唯一写入口是幂等 JSONL 导入
  （默认 dry-run）。
- 导出的分享卡 / 单文件 HTML 可能包含你的真实位置，分享前请自查。

## 许可

MIT —— 见 [LICENSE](LICENSE)。
