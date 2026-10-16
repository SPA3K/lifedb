# LifeDB

> **Your life, one SQLite file.** Local-first personal timeline database —
> locations, photos, workouts, sleep, notes — unified on one time axis.
> Zero upload. Zero telemetry. Your data never leaves your machine.

[中文](README.zh-CN.md) · **English**

*Status: early preview. API may change. Not yet published to PyPI.*

## Why

- **Google killed the Timeline web viewer** — billions of users lost their
  "year in places" map. Your location history shouldn't live on someone
  else's server.
- **Every app owns one slice**: photos here, workouts there, GPS somewhere
  else. Nothing puts them on the **same timeline** — that cross-modal view
  is the one thing no one else has.
- **Privacy is the product**: everything runs locally, including the MCP
  server that apps connect to.

## Architecture

```
App layer     →  your app, via MCP          (we ship small demos only)
MCP server    →  lifedb_mcp.py (localhost)  (the contract)
Kernel        →  SQLite + unified import layer + CLI
```

Apps talk to LifeDB through **MCP tools** — built into Claude Desktop,
Claude Code, or any MCP client. Build your own app layer in any language.

## Quick start (preview)

```bash
git clone <this-repo> && cd life-db
life-db init                       # create timeline.db
life-db ingest events.jsonl        # unified JSONL contract, idempotent
life-db query 2026-10              # one month, all modalities
life-db around 2026-10-13T09:00 --window 2h   # what happened around then
life-db stats                      # coverage & counts
```

### Connect via MCP (Claude Desktop / Claude Code)

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

Tools: `lifedb_stats` · `lifedb_query_month` · `lifedb_around` ·
`lifedb_geo_track` · `lifedb_export_atlas` · `lifedb_ingest_jsonl` ·
`lifedb_adapters`

## Data sources

Import adapters are **plugins** — a manifest + one script. Currently
supported: phone GPS tracks, 训记 (xunji) workouts, Apple Health export,
Google Timeline, photo EXIF, iCloud sync.

Want your app? See the roadmap in [docs/PRODUCT.md](docs/PRODUCT.md) §3.3
(GPX/FIT, Hevy, Strava, Takeout, Obsidian …) — PRs welcome.

## Privacy

- No accounts, no cloud, no telemetry.
- The MCP server binds to stdio / localhost only.
- No arbitrary SQL is exposed — read tools are indexed queries,
  the single write path is idempotent JSONL ingest (dry-run by default).
- Exported share cards / single-file HTML may contain your real locations —
  review before sharing.

## License

MIT — see [LICENSE](LICENSE).
