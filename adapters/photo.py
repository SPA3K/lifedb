#!/usr/bin/env python
"""photo adapter — 本地图库目录(icloudpd 下载落点) → life-db

扫描规则:
  递归扫 <dir> 下 jpg/jpeg/heic/heif/png/webp → 图片事件
  mov/mp4 → 视频事件 (Live Photo 视频半, 若与同名图片配对则并入图片行 meta.live=true, 不单独成行)

时间戳: EXIF DateTimeOriginal > EXIF DateTime > 文件 mtime
  (icloudpd 建议带 --set-exif-datetime, 无 EXIF 的也有保底)
GPS:     EXIF GPS IFD → 十进制 lat/lon (可与 geo_point/停留段跨模态关联)
幂等:    payload_hash = sha1(relpath|size); payload_ref = 相对路径(指针, 不复制正文)
去重:    UNIQUE(source, payload_hash) + INSERT OR IGNORE → 重复扫描安全

用法: py -3 adapters/photo.py <图库根目录> [--dry-run]
"""
import hashlib, json, os, sqlite3, sys
from datetime import datetime

DB_PATH = os.path.expanduser("~/.hermes/life-db/timeline.db")
SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")

IMG_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp"}
VID_EXT = {".mov", ".mp4"}
LIVE_SUFFIX = "_HEVC"          # icloudpd live-photo-mov-filename-policy=suffix

def exif_of(path):
    """返回 (datetime|None, lat|None, lon|None)"""
    try:
        from PIL import Image
        from pillow_heif import register_heif_opener
        register_heif_opener()
        with Image.open(path) as im:
            ex = im.getexif()
            if not ex:
                return None, None, None
            dt = ex.get(36867) or ex.get(306)   # DateTimeOriginal / DateTime
            t = None
            if dt:
                try:
                    t = datetime.strptime(dt.strip()[:19], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    t = None
            lat = lon = None
            try:
                gps = ex.get_ifd(0x8825)
                if gps:
                    def dms(key, ref_key):
                        v = gps.get(key)
                        if not v: return None
                        d, m, s = [float(x) for x in v[:3]]
                        val = d + m / 60 + s / 3600
                        if str(gps.get(ref_key, "N")).upper() in ("S", "W"):
                            val = -val
                        return val
                    lat, lon = dms(2, 1), dms(4, 3)
            except Exception:
                lat = lon = None
            return t, lat, lon
    except Exception:
        return None, None, None

def video_dt(path):
    """ffprobe creation_time > mtime"""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        s = r.stdout.strip().replace("Z", "+00:00")
        if s:
            return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        pass
    return datetime.fromtimestamp(os.path.getmtime(path))

def ingest(root, dry=False):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        sys.exit(f"目录不存在: {root}")
    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as fh:
        con.executescript(fh.read())

    files = []
    for base, _dirs, fns in os.walk(root):
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext in IMG_EXT | VID_EXT:
                files.append(os.path.join(base, fn))
    # 图片先注册 basename 集合 → Live Photo 视频半配对
    stems = {os.path.splitext(os.path.basename(p))[0].replace(LIVE_SUFFIX, "")
             for p in files
             if os.path.splitext(p)[1].lower() in IMG_EXT}
    # 预计算: 哪些图片带有 Live 视频半 (插入图片行时标 meta.live)
    live_imgs = {os.path.splitext(os.path.basename(p))[0][: -len(LIVE_SUFFIX)]
                 for p in files
                 if os.path.splitext(p)[1].lower() == ".mov"
                 and os.path.splitext(os.path.basename(p))[0].endswith(LIVE_SUFFIX)
                 and os.path.splitext(os.path.basename(p))[0][: -len(LIVE_SUFFIX)] in stems}

    n_img = n_vid = n_live = n_skip = 0
    for path in files:
        rel = os.path.relpath(path, root)
        ext = os.path.splitext(path)[1].lower()
        stem = os.path.splitext(os.path.basename(path))[0]
        is_live = ext == ".mov" and stem.endswith(LIVE_SUFFIX) \
                  and stem[: -len(LIVE_SUFFIX)] in stems
        if is_live:
            n_live += 1          # 视频半并入同名图片行, 不单独成行
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            n_skip += 1; continue
        h = hashlib.sha1(f"{rel}|{size}".encode()).hexdigest()[:16]

        if ext in IMG_EXT:
            dt, lat, lon = exif_of(path)
            if dt is None:
                dt = datetime.fromtimestamp(os.path.getmtime(path))
            kind = "image"
            modality = "photo"
            n_img += 1
        else:
            dt, lat, lon = video_dt(path), None, None
            kind = "video"
            modality = "photo"
            n_vid += 1

        meta = {"kind": kind, "size_bytes": size, "ext": ext.lstrip(".")}
        if ext in IMG_EXT and stem in live_imgs:
            meta["live"] = True
        cur = con.execute(
            """INSERT OR IGNORE INTO event
               (ts_start,modality,source,title,payload_ref,payload_hash,lat,lon,tags,meta)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (dt.isoformat(), modality, "icloud", os.path.basename(path),
             rel, h, lat, lon,
             json.dumps(["照片"], ensure_ascii=False),
             json.dumps(meta, ensure_ascii=False)))
        if not cur.rowcount:
            n_skip += 1
    if dry:
        con.rollback()
        print(f"[dry-run] 图片 {n_img} / 视频 {n_vid} / Live半跳过 {n_live} / 已存在 {n_skip}"
              f" —— 已回滚, DB 未变")
    else:
        con.commit()
        print(f"图片 {n_img} + 视频 {n_vid} 扫描, Live半 {n_live} 个并入配对, "
              f"新入库 {n_img + n_vid - n_skip}, 已存在 {n_skip}")

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        sys.exit(__doc__)
    ingest(args[0], dry=dry)
