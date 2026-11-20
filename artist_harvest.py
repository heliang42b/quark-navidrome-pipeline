# -*- coding: utf-8 -*-
"""通用：翻页抓取 flac.music.hi.cn 某歌手全量（kuwo + wyy），生成原始清单。"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flac  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ARTIST = sys.argv[1] if len(sys.argv) > 1 else "林忆莲"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"{ARTIST}_plan.json"


def harvest_platform(platform: str) -> list[dict]:
    out = []
    for page in range(1, 60):
        try:
            rows = flac.search(ARTIST, platform=platform, page=page, size=20)
        except Exception as exc:  # noqa: BLE001
            print(f"  {platform} page {page} FAIL: {str(exc)[:70]}", flush=True)
            time.sleep(5)
            try:
                rows = flac.search(ARTIST, platform=platform, page=page, size=20)
            except Exception:  # noqa: BLE001
                break
        if not rows:
            print(f"  {platform}: 到第 {page} 页为空，共 {len(out)} 条", flush=True)
            break
        out.extend(rows)
        if page % 5 == 0:
            print(f"  {platform} page {page}: 累计 {len(out)}", flush=True)
        time.sleep(1.2)
    return out


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    print(f"抓 {ARTIST} kuwo ...", flush=True)
    kuwo = harvest_platform("kuwo")
    print(f"抓 {ARTIST} wyy ...", flush=True)
    wyy = harvest_platform("wyy")

    print(f"\nkuwo {len(kuwo)} 条，wyy {len(wyy)} 条", flush=True)

    merged: dict[str, dict] = {}
    for rows, plat in ((kuwo, "kuwo"), (wyy, "wyy")):
        for r in rows:
            artist = (r.get("artist") or "").strip()
            title = (r.get("name") or r.get("title") or "").strip()
            if not title or ARTIST not in artist:
                continue
            key = title
            if key not in merged:
                merged[key] = {
                    "title": title, "artist": artist,
                    "album": (r.get("album_name") or "").strip(),
                    "album_id": r.get("album_id") or "",
                    "pic": r.get("pic_url") or "",
                    "duration": r.get("duration") or "",
                    "platform": plat, "id": str(r.get("id")),
                    "minfo": r.get("minfo") or [], "time": r.get("time"), "sign": r.get("sign"),
                }
            elif plat == "kuwo" and merged[key]["platform"] != "kuwo":
                merged[key].update({
                    "album": (r.get("album_name") or "").strip(),
                    "album_id": r.get("album_id") or "",
                    "pic": r.get("pic_url") or "",
                    "duration": r.get("duration") or "",
                    "platform": plat, "id": str(r.get("id")),
                    "minfo": r.get("minfo") or [], "time": r.get("time"), "sign": r.get("sign"),
                })

    plan = [merged[k] for k in sorted(merged)]
    json.dump(plan, open(os.path.join(DATA, OUT), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n_kuwo = sum(1 for p in plan if p["platform"] == "kuwo")
    n_flac = sum(1 for p in plan if any(m.get("level") == "ff" or m.get("format") == "flac"
                                        for m in p["minfo"]))
    print(f"\n去重后 {ARTIST} {len(plan)} 首（kuwo {n_kuwo}，有 FLAC {n_flac}）", flush=True)


if __name__ == "__main__":
    main()
