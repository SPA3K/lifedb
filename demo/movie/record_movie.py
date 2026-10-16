#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""录制人生电影 — 逐帧驱动 T/render (确定性, 不靠实时 rAF)
契约: movie.html 暴露全局 T(视频秒) + render()
用法: py -3 demo/movie/record_movie.py [输出名] [--vert] [--fps 16]
输出: demo/movie/<输出名>.mp4 (+ .gif 720p)
"""
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MDIR = os.path.join(BASE, "demo", "movie")
FPS_STEP = 0.06      # 每帧推进的视频秒 (~16.6fps 有效帧率)


def main():
    name = next((a for a in sys.argv[1:] if not a.startswith("--")), "lifedb-movie")
    vert = "--vert" in sys.argv
    html = os.path.join(MDIR, "movie.html")
    if not os.path.exists(html):
        sys.exit("先生成: py -3 demo/movie/build_movie.py")
    webm = os.path.join(MDIR, f"_{name}.webm")
    mp4 = os.path.join(MDIR, f"{name}.mp4")
    if os.path.exists(webm):
        os.remove(webm)

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        vw, vh = (900, 1600) if vert else (1600, 900)
        ctx = b.new_context(viewport={"width": vw, "height": vh},
                            record_video_dir=MDIR,
                            record_video_size={"width": vw, "height": vh})
        page = ctx.new_page()
        t_rec = time.time()                 # 录制起点 (含页面加载死区, 片尾裁掉)
        page.goto("file:///" + html.replace("\\", "/"))
        page.wait_for_load_state("load")
        time.sleep(2.0)                      # 等底图/照片 base64 解码
        dur = page.evaluate("DUR")
        print(f"电影时长 {dur:.1f}s → {int(dur/FPS_STEP)} 帧")
        n = int(dur / FPS_STEP)
        t_drive = time.time() - t_rec       # 片头死区时长 (裁剪量)
        t0 = time.time()
        for k in range(n):
            page.evaluate("([t])=>{T=t;render()}", [k * FPS_STEP])
            left = t0 + (k + 1) * FPS_STEP - time.time()
            if left > 0:
                time.sleep(left)
        time.sleep(0.8)
        ctx.close()
        video = page.video.path()
        b.close()
    if video != webm:
        os.replace(video, webm)

    r = subprocess.run(["ffmpeg", "-y", "-ss", f"{t_drive:.2f}", "-i", webm,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg 失败:\n" + r.stderr[-800:])
    os.remove(webm)
    print(f"✓ {mp4} ({os.path.getsize(mp4)/1e6:.1f} MB)")

    gif = os.path.join(MDIR, f"{name}.gif")
    r = subprocess.run(["ffmpeg", "-y", "-i", mp4, "-vf",
                        "fps=12,scale=720:-1:flags=lanczos,split[s0][s1];"
                        "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
                        "-loop", "0", gif], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"✓ {gif} ({os.path.getsize(gif)/1e6:.1f} MB)")
    else:
        print("GIF 失败:", r.stderr[-300:])


if __name__ == "__main__":
    main()
