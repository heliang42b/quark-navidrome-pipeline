# -*- coding: utf-8 -*-
"""阶段一：把站点候选歌名拿到 kuwo 上严格校验，生成可下载清单 plan.json。

校验规则（三条都要满足才算「周杰伦原唱」）：
  1. 酷我结果里 artist 必须包含「周杰伦」；
  2. 标题不能带翻唱/伴奏/live/remix 等标记；
  3. 归一化后的标题要和候选歌名对得上（去掉括号补充说明后比较）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kuwo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 结尾的括号补充 / 破折号补充
_TAIL_PAREN = re.compile(r"\s*[\(（\[【][^\(（\[【]*[\)）\]】]\s*$")
_TAIL_DASH = re.compile(r"\s*[\-—–]{1,2}\s*[^\-—–]{1,40}$")


def core(title: str) -> str:
    t = (title or "").strip()
    t = t.replace("\u00a0", " ").replace("&nbsp;", " ")
    t = re.sub(r"\.(mp3|flac|wav|m4a|ape|ogg)$", "", t, flags=re.I)
    # 反复剥掉结尾的括号补充，如 "不该 (with aMEI)"、"千山万水(Single Version)"
    for _ in range(4):
        t2 = _TAIL_PAREN.sub("", t)
        if t2 == t:
            break
        t = t2
    # 再剥掉 " - 中文 R&b2004 周杰" 这种破折号尾巴
    t2 = _TAIL_DASH.sub("", t)
    if len(t2) >= 2:
        t = t2
    t = re.sub(r"^[\s\-_·]+|[\s\-_·]+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def key_of(s: str) -> str:
    """比对用的键：去空格、标点、大小写。"""
    s = re.sub(r"[\s　]+", "", s or "")
    s = re.sub(r"[·・\.\,\，\。\!\！\?\？\'\"“”‘’\(\)（）\[\]【】《》<>]", "", s)
    return s.lower()


def candidates() -> dict[str, dict]:
    rows = json.load(open(os.path.join(DATA, "all.json"), encoding="utf-8"))
    out: dict[str, dict] = {}
    for r in rows:
        artist = (r.get("artist") or "").strip()
        if "周杰伦" not in artist:
            continue
        raw = (r.get("title") or "").strip()
        if not raw:
            continue
        c = core(raw)
        if not c or len(c) > 40:
            continue
        item = out.setdefault(key_of(c), {"core": c, "raw": [], "artists": set()})
        item["raw"].append(raw)
        item["artists"].add(artist)
    for v in out.values():
        v["artists"] = sorted(v["artists"])
    return out


BAD = kuwo.NON_ORIGINAL


def pick(rows: list[dict], target: str) -> dict | None:
    tk = key_of(target)
    best = None
    for r in rows:
        if "周杰伦" not in (r["artist"] or ""):
            continue
        blob = f"{r['title']} {r['fullTitle']} {r['artist']}"
        if any(h in blob for h in BAD):
            continue
        rk = key_of(core(r["title"]))
        if not rk:
            continue
        score = 0
        if rk == tk:
            score = 3
        elif len(tk) >= 3 and (tk in rk or rk in tk):
            score = 2
        else:
            continue
        # 原唱优先：artist 恰好是周杰伦 > 合唱
        if r["artist"].strip() == "周杰伦":
            score += 1
        # 时长合理（>90s）
        if r["duration"] >= 90:
            score += 1
        cand = (score, r)
        if best is None or cand[0] > best[0]:
            best = cand
    return best[1] if best else None


def main() -> None:
    cands = candidates()
    print(f"候选键：{len(cands)}", flush=True)
    plan, missed = [], []
    keys = sorted(cands, key=lambda k: cands[k]["core"])
    for i, k in enumerate(keys, 1):
        c = cands[k]["core"]
        rows = []
        for query in (f"{c} 周杰伦", f"{c}"):
            try:
                rows = kuwo.search(query, rn=45)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i}] {c} 搜索失败：{exc}", flush=True)
                rows = []
            if rows:
                break
            time.sleep(0.8)
        hit = pick(rows, c)
        if hit:
            plan.append({
                "core": c,
                "rid": hit["id"],
                "title": hit["title"],
                "kk_title": hit["fullTitle"],
                "artist": hit["artist"],
                "album": hit["album"],
                "duration": hit["duration"],
                "cover": hit["cover"],
                "site_raw": cands[k]["raw"][:3],
                "site_artists": cands[k]["artists"],
            })
        else:
            missed.append({"core": c, "why": "酷我无匹配原唱", "raw": cands[k]["raw"][:3]})
        if i % 20 == 0:
            print(f"  {i}/{len(keys)}  命中 {len(plan)}", flush=True)
        time.sleep(0.45)

    json.dump(plan, open(os.path.join(DATA, "plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(missed, open(os.path.join(DATA, "missed.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 按 rid 去重（同一首歌不同站点标题可能指向同一 rid）
    seen, uniq = set(), []
    for p in plan:
        if p["rid"] in seen:
            continue
        seen.add(p["rid"])
        uniq.append(p)
    json.dump(uniq, open(os.path.join(DATA, "plan_unique.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n命中 {len(plan)}，按 rid 去重后 {len(uniq)}，未命中 {len(missed)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
