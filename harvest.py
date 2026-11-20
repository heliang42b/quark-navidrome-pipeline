# -*- coding: utf-8 -*-
"""从 so.liumingye.cn（下歌吧）抓取"周杰伦"全部搜索结果。

站点限速：/api/music/search 60s 内 30 次，超了封 180s。
这里用 ~2.7s/页 的节奏（约 22 次/分钟），100 页大约 4~5 分钟。
支持断点续抓：每页落盘到 data/page_XXX.json。
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE = "https://so.liumingye.cn/api/music/search"
KEYWORD = "周杰伦"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DELAY = 2.7


def fetch(page: int, tries: int = 4) -> dict:
    qs = urllib.parse.urlencode({"q": KEYWORD, "page": page, "pageSize": 20})
    url = f"{BASE}?{qs}"
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://so.liumingye.cn/",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":          # 站点无视 Accept-Encoding，直接回 gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code == 429:
                wait = 200  # 被限速，等封禁窗口过去
                print(f"  [429] 被限速，等 {wait}s", flush=True)
                time.sleep(wait)
            else:
                time.sleep(3 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"page {page} 失败：{last}")


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    first_path = os.path.join(DATA, "page_001.json")
    if os.path.exists(first_path):
        first = json.load(open(first_path, encoding="utf-8"))
    else:
        first = fetch(1)
        json.dump(first, open(first_path, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(DELAY)

    total_pages = int(first.get("totalPages") or 0)
    total = int(first.get("total") or 0)
    print(f"total={total} totalPages={total_pages}", flush=True)

    got = 1
    for page in range(2, total_pages + 1):
        path = os.path.join(DATA, f"page_{page:03d}.json")
        if os.path.exists(path):
            got += 1
            continue
        try:
            payload = fetch(page)
        except Exception as exc:  # noqa: BLE001
            print(f"  page {page} 放弃：{exc}", flush=True)
            continue
        json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        got += 1
        if page % 10 == 0:
            print(f"  {page}/{total_pages}", flush=True)
        time.sleep(DELAY)

    # 合并
    rows = []
    seen = set()
    for page in range(1, total_pages + 1):
        path = os.path.join(DATA, f"page_{page:03d}.json")
        if not os.path.exists(path):
            continue
        for it in json.load(open(path, encoding="utf-8")).get("data") or []:
            key = it.get("id")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(it)
    out = os.path.join(DATA, "all.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"合并完成：{len(rows)} 条 -> {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
