#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LifeDB 人生电影 — hero demo (非交互, 自动播放, 面向传播)

分镜 (~42s @1600x900):
  片头 3.2s   世界底图, 11年轨迹点燃, 标题
  章节 11×3s  每年一章: 该年城市底图 + 轨迹按时序点燃 + 年份大字 + 城市标签
              + 最多4张照片弹出 (kenburns 缓推)
  片尾 4.5s   全景 + 统计 (城市/轨迹天/照片/训练日/公里) + 品牌卡
契约: 页面暴露全局 T(视频秒) + render(), 供 record_movie.py 逐帧确定性驱动
依赖: visual/hero_day.py (fetch_basemap/thumb_b64/merc_px), OSM 瓦片 (缓存)
用法: py -3 demo/movie/build_movie.py     输出 demo/movie/movie.html
"""
import datetime
import json
import math
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIS = os.path.join(BASE, "visual")
sys.path.insert(0, VIS)
from hero_day import fetch_basemap, merc_px, thumb_b64  # noqa: E402
from wrapped_data import city_name, hav  # noqa: E402

DB = os.path.expanduser("~/.hermes/life-db/timeline.db")
OUT_DIR = os.path.join(BASE, "demo", "movie")
MAP_DIR = os.path.join(OUT_DIR, "_maps")
W, H = 1600, 900
CST = datetime.timezone(datetime.timedelta(hours=8))
MAXPT = 6000          # 每章轨迹点上限 (均匀抽稀)
MAXPH = 4             # 每章照片数


def year_points(con):
    """按 CST 年份分组的 [ts, la, lo]"""
    out = {}
    for ts, la, lo in con.execute("SELECT ts,lat,lon FROM geo_point ORDER BY ts"):
        y = datetime.datetime.fromtimestamp(ts, CST).year
        out.setdefault(y, []).append((ts, la, lo))
    return out


def km_of(pts):
    s = 0.0
    for i in range(1, len(pts)):
        dt = pts[i][0] - pts[i - 1][0]
        d = hav(pts[i - 1][1:], pts[i][1:])
        if 0 < dt <= 1800 and d <= 300:
            s += d
    return s


def thin(pts, n):
    if len(pts) <= n:
        return pts
    step = len(pts) / n
    out = [pts[int(i * step)] for i in range(n)]
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def densest_center(pts):
    """0.2° 网格最密格中心 — 年度城市标签用"""
    from collections import Counter
    c = Counter((round(la, 1), round(lo, 1)) for _, la, lo in pts)
    if not c:
        return None
    (la, lo), _ = c.most_common(1)[0]
    sub = [(p[1], p[2]) for p in pts
           if abs(p[1] - la) < 0.2 and abs(p[2] - lo) < 0.2]
    return (sum(p[0] for p in sub) / len(sub), sum(p[1] for p in sub) / len(sub))


def fit_bbox(la0, la1, lo0, lo1, w, h, pad=0.06):
    span_la, span_lo = la1 - la0, lo1 - lo0
    la0 -= max(span_la * pad, 0.03); la1 += max(span_la * pad, 0.03)
    lo0 -= max(span_lo * pad, 0.06); lo1 += max(span_lo * pad, 0.06)
    for _ in range(80):                      # 补成 16:9
        x0, y0 = merc_px(la1, lo0, 12)
        x1, y1 = merc_px(la0, lo1, 12)
        if (x1 - x0) / (y1 - y0) >= w / h:
            break
        need = (w / h * (y1 - y0) - (x1 - x0)) / 2
        dlon = need / (256 * (2 ** 12) / 360)
        lo0 -= dlon; lo1 += dlon
    return la0, la1, lo0, lo1


def build():
    con = sqlite3.connect(DB)
    yp = year_points(con)
    photos = con.execute(
        "SELECT ts_start, lat, lon, payload_ref FROM event "
        "WHERE modality='photo' AND lat IS NOT NULL AND NOT (lat=0 AND lon=0) "
        "ORDER BY ts_start").fetchall()
    wk_days = {r[0][:10] for r in con.execute(
        "SELECT DISTINCT ts_start FROM event WHERE modality='workout' "
        "AND source='xunji'")}
    con.close()

    os.makedirs(MAP_DIR, exist_ok=True)
    years = sorted(y for y in yp if len(yp[y]) >= 30)
    chapters, all_pts = [], []
    for y in years:
        pts = yp[y]
        all_pts += pts
        la0 = min(p[1] for p in pts); la1 = max(p[1] for p in pts)
        lo0 = min(p[2] for p in pts); lo1 = max(p[2] for p in pts)
        la0, la1, lo0, lo1 = fit_bbox(la0, la1, lo0, lo1, W, H)
        bm = fetch_basemap(lo0, lo1, la0, la1, int(W * 1.6), int(H * 1.6),
                           os.path.join(MAP_DIR, f"y{y}.jpg"), max_tiles=260)
        if not bm:
            print(f"  ! {y} 底图失败, 跳过"); continue
        path, mx0, my0, k, mw, mh, mz = bm
        ox, oy = (W - mw) / 2, (H - mh) / 2

        def P(la, lo, mx0=mx0, my0=my0, k=k, ox=ox, oy=oy):
            wx, wy = merc_px(la, lo, mz)
            return ox + (wx - mx0) * k, oy + (wy - my0) * k

        ctr = densest_center(pts)
        city = city_name(*ctr) if ctr else None
        if not city and ctr:
            city = f"{ctr[0]:.1f}°N, {ctr[1]:.1f}°E" if ctr[0] >= 0 else \
                   f"{-ctr[0]:.1f}°S, {ctr[1]:.1f}°E"
        yph = []
        cand = [p for p in photos if p[0][:4] == str(y)]
        if cand:
            step = max(1, len(cand) // MAXPH)
            for p in cand[::step][:MAXPH]:
                b64 = thumb_b64(p[3], 480)
                if b64:
                    x, yv = P(p[1], p[2])
                    yph.append(dict(x=round(min(max(x, 220), W - 220)),
                                    y=round(min(max(yv, 170), H - 170)),
                                    img=b64))
        chapters.append(dict(
            year=y, map=os.path.basename(path),
            pts=[[ts, round(la, 5), round(lo, 5)] for ts, la, lo in thin(pts, MAXPT)],
            proj=dict(mx0=mx0, my0=my0, k=k, ox=ox, oy=oy, mz=mz,
                      mw=round(mw), mh=round(mh)),
            city=city or "",
            days=len({datetime.datetime.fromtimestamp(p[0], CST).date() for p in pts}),
            photos=yph))
        print(f"  {y}: {len(pts)}点 {city} 底图{mw:.0f}x{mh:.0f} 照片{len(yph)}")

    # 片头/片尾全景
    la0 = min(p[1] for p in all_pts); la1 = max(p[1] for p in all_pts)
    lo0 = min(p[2] for p in all_pts); lo1 = max(p[2] for p in all_pts)
    la0, la1, lo0, lo1 = fit_bbox(la0, la1, lo0, lo1, W, H, pad=0.10)
    bm = fetch_basemap(lo0, lo1, la0, la1, W * 2, H * 2,
                       os.path.join(MAP_DIR, "world.jpg"), max_tiles=120)
    if not bm:
        sys.exit("全景底图失败")
    path, mx0, my0, k, mw, mh, mz = bm
    ox, oy = (W - mw) / 2, (H - mh) / 2

    def PW(la, lo):
        wx, wy = merc_px(la, lo, mz)
        return ox + (wx - mx0) * k, oy + (wy - my0) * k

    world_pts = [[ts, round(la, 4), round(lo, 4)] for ts, la, lo in thin(all_pts, 14000)]
    stats = dict(
        years=f"{years[0]}–{years[-1]}",
        cities=len({city_name(la, lo) for _, la, lo in thin(all_pts, 20000)
                    if city_name(la, lo)}),
        days=len({datetime.datetime.fromtimestamp(p[0], CST).date()
                  for p in all_pts}),
        photos=len(photos),
        workouts=len(wk_days),
        km=round(sum(km_of(yp[y]) for y in years)),
    )
    payload = dict(world=dict(map=os.path.basename(path), pts=world_pts,
                              proj=dict(mx0=mx0, my0=my0, k=k, ox=ox, oy=oy, mz=mz,
                                        mw=round(mw), mh=round(mh))),
                   chapters=chapters, stats=stats)
    stats["years"] = f"{chapters[0]['year']}–{chapters[-1]['year']}"
    tpl = open(os.path.join(OUT_DIR, "movie_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    fp = os.path.join(OUT_DIR, "movie.html")
    open(fp, "w", encoding="utf-8").write(html)
    print(f"✓ {fp}  ({os.path.getsize(fp)/1e6:.1f} MB)  stats={stats}")
    return fp


if __name__ == "__main__":
    build()
