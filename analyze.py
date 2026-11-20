# -*- coding: utf-8 -*-
"""把抓到的 2000 条站点记录，归并成「周杰伦原唱候选歌单」。"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 出现这些词就当成「非原唱 / 非正式录音室版本」，直接排除
BAD = [
    "翻唱", "翻自", "cover", "Cover", "COVER", "Covered", "改编", "致敬", "模仿",
    "伴奏", "纯音乐", "纯享", "inst", "Instrumental", "karaoke", "KTV", "ktv",
    "DJ", "dj", "Remix", "remix", "混音", "串烧", "慢摇", "电音", "8bit", "抖音",
    "钢琴", "吉他", "古筝", "二胡", "葫芦丝", "口琴", "尤克里里", "笛子", "小提琴",
    "女声", "男声", "童声", "降调", "升调", "变速", "加速", "慢速",
    "铃声", "片段", "搞笑", "恶搞", "现场", "Live", "live", "演唱会", "音乐节",
    "合辑", "精选", "专辑", "无损", "mp3", "MP3", "flac", "FLAC", "wav", "WAV",
    "高音质", "试听", "剪辑", "串烧版", "音乐盒", "八音盒", "轻音乐", "治愈", "睡前",
    "BGM", "bgm", "变调", "消音", "半曲", "副歌", "完整版", "超清", "高清",
]

# 明显不是歌名的条目
NOT_SONG = ["经典重现", "歌曲合集", "全部歌曲", "作品集", "歌单", "合集", "金曲", "全集"]

_CONNECT = re.compile(r"(?:&|＆|/|、|\+)\s*周杰伦|周杰伦\s*(?:&|＆|/|、|\+)")


def norm(title: str) -> str:
    t = (title or "").strip()
    t = t.replace("\u00a0", " ").replace("&nbsp;", " ")
    t = re.sub(r"\.(mp3|flac|wav|m4a|ape|ogg)$", "", t, flags=re.I)
    t = _CONNECT.sub("", t)
    t = re.sub(r"^[\s\-_·]+|[\s\-_·]+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def is_bad(raw: str) -> bool:
    low = raw
    return any(m in low for m in BAD) or any(m in low for m in NOT_SONG)


def main() -> None:
    rows = json.load(open(os.path.join(DATA, "all.json"), encoding="utf-8"))
    print("站点条目：", len(rows))

    artists = Counter((r.get("artist") or "").strip() for r in rows)
    print("\n-- 出现最多的 artist --")
    for a, c in artists.most_common(15):
        print(f"  {c:5d}  {a!r}")

    jay = [r for r in rows if (r.get("artist") or "").strip() == "周杰伦"]
    print(f"\nartist 严格等于「周杰伦」：{len(jay)} 条")

    kept, dropped = {}, []
    for r in jay:
        raw = r.get("title") or ""
        if is_bad(raw):
            dropped.append(raw)
            continue
        n = norm(raw)
        if not n or len(n) > 60:
            dropped.append(raw)
            continue
        kept.setdefault(n, []).append(raw)

    print(f"去重后候选歌名：{len(kept)} 个")
    print(f"被排除条目：{len(dropped)} 条")

    with open(os.path.join(DATA, "candidates.json"), "w", encoding="utf-8") as fh:
        json.dump(sorted(kept), fh, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "dropped.json"), "w", encoding="utf-8") as fh:
        json.dump(dropped, fh, ensure_ascii=False, indent=1)

    print("\n-- 候选（前 60）--")
    for n in sorted(kept)[:60]:
        print("  ", n, "  <=", kept[n][:3])


if __name__ == "__main__":
    sys.exit(main())
