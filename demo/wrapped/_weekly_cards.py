#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本周回顾竖版卡片 — 1080×1920 × 4屏
数据: visual/_weekly_YYYYMMDD.json | 复用年度卡的视觉语言 (WRAPPED-SPEC.md)
屏: ①通勤 ②节奏(7日步数柱) ③训练 ④身体
用法: py -3 _weekly_cards.py 2026-08-24
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[2]        # 仓库根
HERE = Path(__file__).resolve().parent            # demo/wrapped
VIS = BASE / "visual"                             # 本地资产 (fonts/bg, gitignored)
WK = sys.argv[1] if len(sys.argv) > 1 else "2026-08-24"
D = json.load(open(HERE / "out" / f"_weekly_{WK.replace('-', '')}.json", encoding="utf-8"))
c, s, b, o, w = D["commute"], D["steps"], D["body"], D["out"], D["workout"]
WD = "一二三四五六日"

_FONTDIR = VIS / "_fonts"
_bgurl = lambda bg: (VIS / "_bg" / f"{bg}.png").as_uri()
ff = "\n".join(
    f"@font-face{{font-family:'{f}';src:url('{(_FONTDIR / (f + '.ttf')).as_uri()}');font-display:block}}"
    for f in ["MiSans-Light", "MiSans-Regular", "MiSans-Medium", "MiSans-Semibold",
              "MiSans-Bold", "PlayfairDisplay", "BebasNeue-Regular"])


def screen(bg, tab, eyebrow, big, unit, label, items, note, accent="#7dd3fc",
           bgfilter="", extra=""):
    lis = "".join(
        f'<div class="item"><span class="in">{a}</span><span class="iv">{b_}</span></div>'
        for a, b_ in items)
    f = f";filter:{bgfilter}" if bgfilter else ""
    return f"""
<div class="screen">
  <div class="bg" style="background-image:url('{_bgurl(bg)}'){f}"></div>
  <div class="veil"></div>
  <div class="edge" style="color:{accent}cc">{tab} / 04</div>
  <div class="body">
    <div class="eyebrow" style="color:{accent}">{eyebrow}</div>
    <div class="bignum">{big}<span class="unit">{unit}</span></div>
    <div class="label">{label}</div>
    {extra}
    <div class="items">{lis}</div>
  </div>
  <div class="note">{note}</div>
</div>"""


def bars_html():
    mx = max(s["per_day"].values()) or 1
    cols = ""
    for i, (d, v) in enumerate(s["per_day"].items()):
        h = round(v / mx * 340)
        peak = " style=\"background:linear-gradient(180deg,#fff 0%,#b9a6ff 100%)\"" if v == mx else ""
        cols += (f'<div class="bar"><div class="bv">{round(v/1000,1)}k</div>'
                 f'<div class="bh" style="height:{h}px"{peak}></div>'
                 f'<div class="bl">{WD[i]}</div></div>')
    return f'<div class="bars">{cols}</div>'


def wd_label(iso):
    from datetime import datetime
    return "周" + WD[datetime.strptime(iso, "%Y-%m-%d").weekday()]


delta_steps = (s["total"] / s["prev_total"] - 1) * 100 if s["prev_total"] else 0
rhr_d = b["rhr"] - b["rhr_prev"] if b["rhr"] is not None and b["rhr_prev"] is not None else None
hrv_d = b["hrv"] - b["hrv_prev"] if b["hrv"] is not None and b["hrv_prev"] is not None else None
earliest = c["earliest"]
leg = {"2026-08-24": "腿", "2026-08-25": "肩臂", "2026-08-26": "背", "2026-08-29": "腿"}

screens = [
    screen("cover", "通勤", "八月末周 · COMMUTE", f"{c['avg_minutes']}", " 分钟",
           "平均通勤用时",
           [("通勤天数", f"{c['n']}/5"), ("平均出门", c["avg_departure"]),
            ("平均到岗", c["avg_arrival"]), ("单程", f"{c['km']} km")],
           f"口径：晨间 GPS 轨迹 —— 家锚点（夜间停留中位点）出发，抵达公司锚点（工作日午后停留中位点）800m 内 · 最早出门：{wd_label(earliest[0])} {earliest[1]['departure']}",
           "#8fb8ff", "brightness(1.9) contrast(1.08) saturate(1.15)"),

    screen("night", "节奏", "八月末周 · RHYTHM", f"{s['total']/10000:.1f}", " 万步",
           f"比上周 {delta_steps:+.0f}%",
           [("最高", f"{wd_label(max(s['per_day'], key=s['per_day'].get))} {max(s['per_day'].values()):,.0f}"),
            ("最低", f"{wd_label(min(s['per_day'], key=s['per_day'].get))} {min(s['per_day'].values()):,.0f}"),
            ("出门天数", f"{o['away_days']}/7"), ("过夜", "武汉 " + str(o['nights'].count("武汉")) + " 晚")],
           "步数按 Apple 健康逐日聚合求和 · 环比对象为前一个 7 天窗口 · 夜间过夜地取当日 00–05 时最后一个 GPS 点",
           "#9d8bff", "", bars_html()),

    screen("workout", "训练", "八月末周 · TRAIN", f"{w['volume_kg']/1000:.1f}", " 吨",
           "本周举起的重量",
           [(f"{wd_label(x['date'])} · {leg.get(x['date'],'')}", f"{x['volume_kg']/1000:.1f} 吨 · {x['sets']} 组")
            for x in w["detail"]],
           f"训记口径：各组重量求和 · 共 {w['days']} 练 {w['sets']} 组 · 最大容量来自周六腿日（哈克机深蹲 · 腿举）",
           "#ffb86b"),

    screen("health", "身体", "八月末周 · BODY", f"{b['rhr']:.0f}", " bpm",
           f"静息心率 · 比上周 {rhr_d:+.1f}" if rhr_d is not None else "静息心率",
           [("HRV", f"{b['hrv']:.1f} ms" + (f"（上周 {b['hrv_prev']}）" if b['hrv_prev'] else "")),
            ("走行距离", f"{o['dist_km']} km"),
            ("日照采集", f"{o['daylight_min']} 分钟"),
            ("采样", f"RHR {b['rhr_n']} 天 · HRV {b['hrv_n']} 天")],
           "静息心率 / HRV 为周内 Apple 逐日采样的均值，采样天数有限，趋势仅供参考 · 走行距离为每日 DistanceWalkingRunning 求和",
           "#6be8d4"),
]

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{ff}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;background:#0a0e1a}}
.screen{{position:relative;width:1080px;height:1920px;overflow:hidden;
  font-family:'MiSans-Regular',sans-serif;color:#fff}}
.bg{{position:absolute;inset:0;background-size:cover;background-position:center}}
.veil{{position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(8,12,24,.45) 0%,rgba(8,12,24,.25) 30%,rgba(8,12,24,.78) 78%,rgba(8,12,24,.92) 100%)}}
.edge{{position:absolute;top:64px;right:72px;font-family:'MiSans-Medium';font-size:26px;
  color:rgba(160,190,235,.55);letter-spacing:6px}}
.body{{position:absolute;left:84px;right:84px;top:50%;transform:translateY(-52%)}}
.eyebrow{{font-family:'MiSans-Medium';font-size:34px;color:#7dd3fc;letter-spacing:14px;
  margin-bottom:52px}}
.bignum{{font-family:'PlayfairDisplay',serif;font-size:340px;line-height:.95;
  background:linear-gradient(180deg,#ffffff 30%,#7fa8e8 100%);
  -webkit-background-clip:text;color:transparent;letter-spacing:-6px}}
.unit{{font-family:'MiSans-Light';font-size:92px;color:#a8c6f0;-webkit-text-fill-color:#a8c6f0;
  margin-left:26px;letter-spacing:2px}}
.label{{font-family:'MiSans-Light';font-size:76px;color:#dbe7fb;letter-spacing:22px;
  margin:44px 0 88px;text-shadow:0 2px 18px rgba(0,0,0,.7),0 0 44px rgba(8,12,24,.9)}}
.items{{border-top:1px solid rgba(140,170,220,.28)}}
.item{{display:flex;justify-content:space-between;align-items:baseline;
  padding:34px 6px;border-bottom:1px solid rgba(140,170,220,.28)}}
.in{{font-family:'MiSans-Regular';font-size:40px;color:#9db4d8;letter-spacing:6px}}
.iv{{font-family:'BebasNeue-Regular',sans-serif;font-size:66px;color:#fff;letter-spacing:3px}}
.note{{position:absolute;left:84px;right:84px;bottom:76px;font-family:'MiSans-Regular';
  font-size:24px;line-height:1.6;color:rgba(150,172,208,.52)}}
.bars{{display:flex;justify-content:space-between;align-items:flex-end;height:430px;
  margin:0 10px 76px;border-bottom:1px solid rgba(140,170,220,.35)}}
.bar{{display:flex;flex-direction:column;align-items:center;width:112px}}
.bv{{font-family:'BebasNeue-Regular';font-size:38px;color:#c9d6f2;letter-spacing:2px;
  margin-bottom:14px}}
.bh{{width:64px;border-radius:10px 10px 0 0;
  background:linear-gradient(180deg,#7a6fd8 0%,#4b458f 100%)}}
.bl{{font-family:'MiSans-Regular';font-size:32px;color:#9db4d8;margin-top:18px}}
</style></head><body>{''.join(screens)}</body></html>"""

out = HERE / "out" / "_weekly_cards.html"
open(out, "w", encoding="utf-8").write(html)
names = ["commute", "rhythm", "train", "body"]
with sync_playwright() as pw:
    b_ = pw.chromium.launch(channel="chrome", headless=True)
    pg = b_.new_page(viewport={"width": 1080, "height": 1920})
    pg.goto(out.as_uri())
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(3000)
    for i, nm in enumerate(names):
        el = pg.query_selector_all(".screen")[i]
        el.screenshot(path=str(HERE / "out" / f"wk_{WK.replace('-', '')}-{i+1:02d}_{nm}.png"))
        print("OK", nm)
    b_.close()

# 横向拼接 → 周总结长图
import subprocess
out_dir = HERE / "out"
args = ["ffmpeg", "-y", "-loglevel", "error"]
for i, nm in enumerate(names):
    args += ["-i", str(out_dir / f"wk_{WK.replace('-', '')}-{i+1:02d}_{nm}.png")]
args += ["-filter_complex", "[0][1][2][3]hstack=inputs=4",
         str(out_dir / f"wk_{WK.replace('-', '')}-strip.png")]
subprocess.run(args, check=True)
print("OK strip")
