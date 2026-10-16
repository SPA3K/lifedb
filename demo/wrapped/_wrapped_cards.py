#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Wrapped 竖版卡片生成 — 1080×1920 × 5屏
数据: visual/_wrapped2026.json | 背景: visual/_bg/*.png | 字体: A方案(Playfair+MiSans)
规范: visual/WRAPPED-SPEC.md — 正文只给结果, 口径小字在底部
"""
import json, os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[2]        # 仓库根
HERE = Path(__file__).resolve().parent            # demo/wrapped
VIS = BASE / "visual"                             # 本地资产 (fonts/bg, gitignored)
D = json.load(open(HERE / "out" / "_wrapped2026.json", encoding="utf-8"))
n, w, p, h = D["nights"], D["workout"], D["photos"], D["health"]
cities_n = [c for c in n["cities"] if c["city"] != "?"][:6]
cities_p = [c for c in p["cities"] if c["city"] != "?"][:6]
wuhan = cities_n[0]

_FONTDIR = VIS / "_fonts"
_bgurl = lambda bg: (VIS / "_bg" / f"{bg}.png").as_uri()
ff = "\n".join(
    f"@font-face{{font-family:'{f}';src:url('{(_FONTDIR / (f + '.ttf')).as_uri()}');font-display:block}}"
    for f in ["MiSans-Light", "MiSans-Regular", "MiSans-Medium", "MiSans-Semibold",
              "MiSans-Bold", "PlayfairDisplay", "BebasNeue-Regular"])

def screen(idx, bg, tab, eyebrow, big, unit, label, items, note, accent="#7dd3fc",
           bgfilter=""):
    lis = "".join(
        f'<div class="item"><span class="in">{a}</span><span class="iv">{b}</span></div>'
        for a, b in items)
    f = f";filter:{bgfilter}" if bgfilter else ""
    return f"""
<div class="screen">
  <div class="bg" style="background-image:url('{_bgurl(bg)}'){f}"></div>
  <div class="veil"></div>
  <div class="edge" style="color:{accent}cc">{tab} / 05</div>
  <div class="body">
    <div class="eyebrow" style="color:{accent}">{eyebrow}</div>
    <div class="bignum">{big}<span class="unit">{unit}</span></div>
    <div class="label">{label}</div>
    <div class="items">{lis}</div>
  </div>
  <div class="note">{note}</div>
</div>"""

screens = [
    screen(1, "cover", "封面", "二〇二六 · 年度回望", "2026", "", "我的时间都去了哪里",
           [("被 GPS 见证的夜晚", "196"), ("训练日", f"{w['days']}"),
            ("带定位的照片", f"{p['total']}"), ("城市足迹", f"{len(cities_p)}")],
           "全年有 GPS 证据的当地日统计 · 数据来源：一生轨迹 / iCloud / Apple 健康 · 全部本地计算",
           "#8fb8ff", "brightness(1.9) contrast(1.08) saturate(1.15)"),

    screen(2, "night", "夜晚", "夜晚 · NIGHT", f"{n['total']}", " 晚",
           "被 GPS 见证",
           [("主卧 武汉", f"{wuhan['nights']} 晚"), ("据点", f"{wuhan['sites']} 处"),
            ("首尔", f"{(cities_n[1]['nights'] if len(cities_n)>1 else 0)} 晚"),
            ("移动夜", f"{n['moving']}")],
           "夜间手机静默日不计入 · 当地日按 GPS 所在时区切分 · 末点规则为夜间缺数时的兜底",
           "#9d8bff"),

    screen(3, "workout", "训练", "训练 · TRAIN", f"{w['volume_kg']/1000:.0f}", " 吨",
           "全年举起的重量",
           [("训练日", f"{w['days']}"), ("组数", f"{w['sets']}"),
            ("锻炼轨迹", f"{w['routes']} 条"), ("轨迹公里", f"{w['route_km']} km")],
           f"力量容量 {w['volume_kg']:,.0f} kg = 训记各组重量求和 · 训练日含训记与 Apple 锻炼",
           "#ffb86b"),

    screen(4, "health", "健康", "健康 · HEALTH", f"{h['steps_total']/10000:.0f}", " 万步",
           "走过的路都算数",
           [("最猛一天", f"{h['steps_best_n']/10000:.1f} 万"), ("日期", h["steps_best_day"]),
            ("静息心率", f"{h['rest_hr']}"), ("心电图", f"{h['ecg_n']} 次")],
           f"静息心率取 Apple 每日一次采样的年内均值（{h['rest_hr_days']} 天有采样）· 步数按日聚合求和",
           "#6be8d4"),

    screen(5, "travel", "旅行", "足迹 · PLACES", f"{len(cities_p)}", " 城",
           "镜头对准过的地方",
           [(c["city"], f"{c['n']} 张") for c in cities_p[:4]],
           f"照片聚簇反推 · {p['total']} 张带定位照片 · 每城统计年内落点数",
           "#ffd98b"),
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
  margin:44px 0 96px}}
.items{{border-top:1px solid rgba(140,170,220,.28)}}
.item{{display:flex;justify-content:space-between;align-items:baseline;
  padding:34px 6px;border-bottom:1px solid rgba(140,170,220,.28)}}
.in{{font-family:'MiSans-Regular';font-size:40px;color:#9db4d8;letter-spacing:6px}}
.iv{{font-family:'BebasNeue-Regular',sans-serif;font-size:66px;color:#fff;letter-spacing:3px}}
.note{{position:absolute;left:84px;right:84px;bottom:76px;font-family:'MiSans-Regular';
  font-size:24px;line-height:1.6;color:rgba(150,172,208,.52)}}
</style></head><body>{''.join(screens)}</body></html>"""

out = HERE / "out" / "_wrapped_cards.html"
open(out, "w", encoding="utf-8").write(html)
names = ["cover", "night", "workout", "health", "travel"]
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1080, "height": 1920})
    pg.goto(out.as_uri())
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(3000)
    for i, nm in enumerate(names):
        el = pg.query_selector_all(".screen")[i]
        el.screenshot(path=str(HERE / "out" / f"_wc_{i+1:02d}_{nm}.png"))
        print("OK", nm)
    b.close()
