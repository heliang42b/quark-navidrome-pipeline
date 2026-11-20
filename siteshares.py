# -*- coding: utf-8 -*-
"""阶段 A（不需要夸克登录）：
1) 从站点清单里按歌名归并，挑出每首「音质最高」的那条记录；
2) 逐条打 /api/music/{id} 拿到夸克分享链接。

产物：data/targets.json / data/shares.json
"""
from __future__ import annotations

import gzip
import json
import os
import random
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import build_candidates, core, key_of, safe_name  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

# 音质优先级：数字越大越好
RANK = [
    ("夸克FLAC", 90), ("FLAC", 90), ("夸克WAV", 80), ("WAV", 80),
    ("夸克APE", 85), ("APE", 85),
    ("夸克MP3", 50), ("MP3", 50), ("夸克网盘", 20), ("百度云", 10),
]


def qrank(quality: list[str]) -> int:
    best = 0
    for q in quality or []:
        for key, val in RANK:
            if key in str(q):
                best = max(best, val)
    return best


def build_targets() -> list[dict]:
    rows = json.load(open(os.path.join(DATA, "all.json"), encoding="utf-8"))
    cands = {key_of(c["core"]): c for c in build_candidates()}
    best: dict[str, dict] = {}
    for r in rows:
        artist = (r.get("artist") or "").strip()
        if "周杰伦" not in artist:
            continue
        raw = (r.get("title") or "").strip()
        k = key_of(core(raw))
        if k not in cands:
            continue
        score = qrank(r.get("quality") or [])
        if score <= 0:
            continue
        cur = best.get(k)
        if cur is None or score > cur["score"]:
            best[k] = {
                "key": k,
                "core": cands[k]["core"],
                "entry_id": r["id"],
                "site_title": raw,
                "artist_hint": artist,
                "quality": r.get("quality"),
                "score": score,
                "cover": r.get("cover") or "",
            }
    return [best[k] for k in sorted(best)]


def site_detail(entry_id: str) -> dict | None:
    url = f"https://so.liumingye.cn/api/music/{entry_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://so.liumingye.cn/",
        "Accept": "application/json"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8", "replace"))


def main() -> None:
    targets = build_targets()
    print(f"目标歌曲：{len(targets)} 首", flush=True)
    json.dump(targets, open(os.path.join(DATA, "targets.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    shares_path = os.path.join(DATA, "shares.json")
    shares = {}
    if os.path.exists(shares_path):
        try:
            shares = json.load(open(shares_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            shares = {}

    for i, t in enumerate(targets, 1):
        k = t["key"]
        if k in shares and shares[k].get("downloads"):
            continue
        try:
            d = site_detail(t["entry_id"])
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] {t['core']} 详情失败 {str(exc)[:50]}", flush=True)
            time.sleep(3)
            continue
        dls = d.get("downloads") or []
        best = None
        for item in dls:
            sc = qrank([item.get("quality")])
            if best is None or sc > best["score"]:
                best = {"url": item.get("url"), "quality": item.get("quality"), "score": sc}
        if best and best.get("url"):
            shares[k] = {
                "core": t["core"],
                "quality": best["quality"],
                "url": best["url"],
                "lyrics": d.get("lyrics") or "",
                "cover": d.get("cover") or "",
                "artist": d.get("artist") or "周杰伦",
                "site_title": d.get("title") or t["site_title"],
                "all": dls,
            }
        else:
            print(f"[{i}] {t['core']} 没有网盘链接", flush=True)
        if i % 10 == 0:
            json.dump(shares, open(shares_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(f"  {i}/{len(targets)}  已拿到 {len(shares)}", flush=True)
        time.sleep(2.4 + random.uniform(0, 0.8))

    json.dump(shares, open(shares_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    c = Counter(v["quality"] for v in shares.values())
    print(f"\n完成：{len(shares)} 首有链接；音质分布 {dict(c)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
