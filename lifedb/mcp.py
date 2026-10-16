#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lifedb MCP 服务 — 内核能力的唯一对外契约 (v0.1)

架构见 docs/PRODUCT.md §4:
  - stdio 传输, 仅本机; 不暴露任意 SQL
  - 读工具全部走索引 range seek (禁 LIKE 前缀, 见 kernel 约定)
  - 唯一写入口 lifedb_ingest_jsonl, 默认 dry_run=True, 幂等 (payload_hash)
  - DB 路径: LIFEDB_DB 环境变量, 默认 ~/.hermes/life-db/timeline.db

运行: py -3 mcp_server.py          (或被 MCP 客户端以 stdio 拉起)
契约变更规则: 工具只增不改不删; 改动 = 大版本
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

try:                                    # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:             # mcp 2.x: FastMCP → MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

CST = timezone(timedelta(hours=8))
DB = os.environ.get("LIFEDB_DB") or os.path.join(
    os.path.expanduser("~"), ".hermes", "life-db", "timeline.db")

mcp = FastMCP("lifedb",
              instructions="LifeDB — local-first personal timeline DB. "
                          "Use lifedb_stats first to see coverage, then "
                          "lifedb_query_month / lifedb_around for events, "
                          "lifedb_geo_track / lifedb_export_atlas for maps.")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _event_row(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in r.keys() if k != "payload_hash"}
    for k in ("tags", "meta"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


@mcp.tool()
def lifedb_stats() -> str:
    """库自检: schema 版本、各模态/来源计数、时间覆盖。应用接入后先调这个。"""
    con = connect()
    try:
        try:
            v = con.execute("SELECT version FROM schema_version "
                            "WHERE name='lifedb'").fetchone()[0]
        except sqlite3.OperationalError:
            return json.dumps({"error": "not initialized (跑 life-db init)"},
                              ensure_ascii=False)
        total = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        mods = {r[0]: r[1] for r in con.execute(
            "SELECT modality, COUNT(*) FROM event GROUP BY modality ORDER BY 2 DESC")}
        srcs = {r[0]: r[1] for r in con.execute(
            "SELECT source, COUNT(*) FROM event GROUP BY source ORDER BY 2 DESC")}
        span = con.execute("SELECT MIN(ts_start), MAX(ts_start) "
                           "FROM event").fetchone()
        geo = con.execute("SELECT COUNT(*) FROM geo_point").fetchone()[0]
        return json.dumps(dict(schema_version=v, events=total, geo_points=geo,
                               modalities=mods, sources=srcs,
                               span=[span[0], span[1]]), ensure_ascii=False)
    finally:
        con.close()


@mcp.tool()
def lifedb_query_month(month: str, limit: int = 200, offset: int = 0) -> str:
    """某月时间线。month 形如 '2026-10'。返回统一 schema 事件行 (ts_start 升序)。"""
    y, m = (int(x) for x in month.split("-"))
    lo = f"{y:04d}-{m:02d}"
    hi = f"{y + (m == 12):04d}-{1 if m == 12 else m + 1:02d}"
    con = connect()
    try:
        rows = con.execute(
            "SELECT * FROM event WHERE ts_start >= ? AND ts_start < ? "
            "ORDER BY ts_start LIMIT ? OFFSET ?", (lo, hi, limit, offset)).fetchall()
        return json.dumps([_event_row(r) for r in rows], ensure_ascii=False,
                          default=str)
    finally:
        con.close()


@mcp.tool()
def lifedb_around(ts: str, window: str = "2h", limit: int = 200) -> str:
    """跨模态事件窗: ts 前后 window (如 '30m'/'2h'/'1d') 内发生的所有事件。
    三分支 UNION, 全索引 seek。用于'那一刻发生了什么'。"""
    center = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    unit, n = window[-1], int(window[:-1])
    delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n),
             "d": timedelta(days=n)}.get(unit)
    if not delta:
        return json.dumps({"error": f"bad window {window} (30m/2h/1d)"})
    lo, hi = (center - delta).isoformat(), (center + delta).isoformat()
    con = connect()
    try:
        rows = con.execute(
            """SELECT * FROM event WHERE id IN (
                 SELECT id FROM event WHERE ts_start >= ? AND ts_start <= ?
                 UNION SELECT id FROM event WHERE ts_end >= ? AND ts_end <= ?
                 UNION SELECT id FROM event WHERE ts_end > ? AND ts_start < ?
               ) ORDER BY ts_start LIMIT ?""",
            (lo, hi, lo, hi, hi, lo, limit)).fetchall()
        return json.dumps([_event_row(r) for r in rows], ensure_ascii=False,
                          default=str)
    finally:
        con.close()


def _epoch(x):
    return int(x) if str(x).isdigit() else int(
        datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp())


def _track_rows(t0, t1, limit):
    """GPS 点查询 + 均匀抽稀 (超限时保首尾)。返回 (rows, total)"""
    con = connect()
    try:
        total = con.execute("SELECT COUNT(*) FROM geo_point WHERE ts>=? AND ts<?",
                            (t0, t1)).fetchone()[0]
        if total <= limit:
            rows = con.execute("SELECT ts,lat,lon,alt,speed FROM geo_point "
                               "WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1)).fetchall()
        else:
            step = -(-total // limit)
            rows = con.execute(
                "SELECT ts,lat,lon,alt,speed FROM geo_point "
                "WHERE ts>=? AND ts<? AND ((rowid - (SELECT MIN(rowid) FROM geo_point "
                "WHERE ts>=? AND ts<?)) % ?) = 0 ORDER BY ts",
                (t0, t1, t0, t1, step)).fetchall()
        return rows, total
    finally:
        con.close()


@mcp.tool()
def lifedb_geo_track(start: str, end: str, limit: int = 5000) -> str:
    """原始 GPS 点序列 [ts(epoch秒), lat, lon, alt, speed]。
    start/end 为 ISO 时间或 epoch 秒。轨迹渲染 (deck.gl TripsLayer / Manim) 喂这个。
    limit 截断时按均匀抽稀前置 (取首尾), 避免只截头部。"""
    t0, t1 = _epoch(start), _epoch(end)
    rows, total = _track_rows(t0, t1, limit)
    return json.dumps(dict(total=total, returned=len(rows),
                           step=(-(-total // limit) if total > limit else 1),
                           points=[list(r) for r in rows]), ensure_ascii=False)


@mcp.tool()
def lifedb_export_atlas(start: str, end: str,
                        modalities: str = "", max_points: int = 20000) -> str:
    """一站式打包某时间窗的 atlas 数据: {track(抽稀GPS), events(逗号分隔的模态
    名可选过滤), photos(带坐标照片)}。地图类应用 (Life Atlas/vlog) 的数据源。"""
    lo, hi = datetime.fromtimestamp(_epoch(start), CST).isoformat(), \
        datetime.fromtimestamp(_epoch(end), CST).isoformat()
    mods = [m.strip() for m in modalities.split(",") if m.strip()]
    con = connect()
    try:
        q, args = "SELECT * FROM event WHERE ts_start >= ? AND ts_start < ?", \
            [lo, hi]
        if mods:
            q += " AND modality IN (%s)" % ",".join("?" * len(mods))
            args += mods
        events = [_event_row(r) for r in con.execute(
            q + " ORDER BY ts_start LIMIT ?", (*args, max_points)).fetchall()]
        photos = [dict(ts=r[0], lat=r[1], lon=r[2]) for r in con.execute(
            "SELECT ts_start, lat, lon FROM event WHERE modality='photo' "
            "AND lat IS NOT NULL AND ts_start >= ? AND ts_start < ? "
            "ORDER BY ts_start", (lo, hi)).fetchall()]
    finally:
        con.close()
    rows, total = _track_rows(_epoch(start), _epoch(end), max_points)
    trk = dict(total=total, returned=len(rows),
               step=(-(-total // max_points) if total > max_points else 1),
               points=[list(r) for r in rows])
    return json.dumps(dict(track=trk, events=events, photos=photos),
                      ensure_ascii=False, default=str)


@mcp.tool()
def lifedb_ingest_jsonl(path: str, dry_run: bool = True) -> str:
    """导入统一 JSONL 事件文件 (每行一个 JSON, ts_start/modality/source 必填)。
    幂等: payload_hash=sha256(source|payload_ref|ts_start)[:16] 去重, 重复跑零副作用。
    默认 dry_run=True 只报预览; 明确传 dry_run=false 才写入。"""
    con = connect()
    ins = skip = err = 0
    preview = []
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    err += 1
                    continue
                if not all(e.get(k) for k in ("ts_start", "modality", "source")):
                    err += 1
                    continue
                ph = e.get("payload_hash") or hashlib.sha256(
                    f"{e['source']}|{e.get('payload_ref','')}|{e['ts_start']}"
                    .encode()).hexdigest()[:16]
                if dry_run:
                    exists = con.execute(
                        "SELECT 1 FROM event WHERE payload_hash=?", (ph,)
                    ).fetchone()
                    skip += bool(exists)
                    ins += not exists
                    if len(preview) < 3:
                        preview.append(f"{e['ts_start']} [{e['modality']}]")
                    continue
                cur = con.execute(
                    """INSERT OR IGNORE INTO event
                       (ts_start,ts_end,modality,source,title,summary,payload_ref,
                        payload_hash,lat,lon,tags,meta)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (e["ts_start"], e.get("ts_end"), e["modality"], e["source"],
                     e.get("title"), e.get("summary"), e.get("payload_ref"), ph,
                     e.get("lat"), e.get("lon"),
                     json.dumps(e.get("tags", []), ensure_ascii=False),
                     json.dumps(e.get("meta", {}), ensure_ascii=False)))
                ins += cur.rowcount
                skip += not cur.rowcount
        if not dry_run:
            con.commit()
        return json.dumps(dict(dry_run=dry_run, inserted=ins, deduped=skip,
                               invalid=err, preview=preview), ensure_ascii=False)
    finally:
        con.close()


def _adapters_dir():
    """包内 adapters 优先; 源码仓库布局回退到仓库根 (lifedb/../adapters)"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "adapters"),
              os.path.join(os.path.dirname(here), "adapters")):
        if os.path.isdir(d):
            return d
    return os.path.join(os.path.dirname(here), "adapters")


@mcp.tool()
def lifedb_adapters() -> str:
    """列出全部数据源 adapter (adapters/*.manifest.json): 名称/模态/模式/幂等机制。
    manifest 即插件契约, 见 docs/PRODUCT.md §3。"""
    ad_dir = _adapters_dir()
    out = []
    if os.path.isdir(ad_dir):
        for fn in sorted(f for f in os.listdir(ad_dir)
                         if f.endswith(".manifest.json")):
            try:
                with open(os.path.join(ad_dir, fn), encoding="utf-8") as fh:
                    m = json.load(fh)
                out.append({k: m.get(k) for k in
                            ("name", "implements", "modality", "mode",
                             "dry_run", "status", "cmd", "notes")})
            except (json.JSONDecodeError, OSError):
                continue
    return json.dumps(out, ensure_ascii=False)


def main():
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
