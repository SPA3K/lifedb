#!/usr/bin/env python3
"""xunji helper — 训记API封装(gzip自动解压)"""
import gzip, io, json, time, urllib.request, urllib.error

ENV = open(r"C:\Users\shiel\workspace\life-db\.env.xunji").read()
KEYS = dict(l.split("=", 1) for l in ENV.splitlines() if "=" in l and not l.startswith("#"))

def post(url, key, payload, retries=3):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key.strip(),
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    })
    for attempt in range(retries):
        try:
            r = urllib.request.urlopen(req, timeout=60)
            raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if "frequent" in detail.lower() and attempt < retries - 1:
                wait = 16
                print(f"  限频, 等{wait}s重试...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}")
    raise RuntimeError("retries exhausted")

def trains(datestr, full=False):
    return post("https://trains.xunjiapp.cn/api_trains_for_llm_v2", KEYS["XJLLM_KEY"], {
        "schema_version": "train_open_api_v2",
        "datestr": datestr,
        "include_full_data": full,
    })
