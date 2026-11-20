# -*- coding: utf-8 -*-
"""清理曲库：删非周杰伦、翻唱、噪音、重复文件。

- 删除清单（明确非原唱/非周杰伦/噪音）
- 重复文件：保留干净名，删 "-周杰伦" / "周杰伦+-+" / "周杰伦 - ." 变体
"""
from __future__ import annotations

import os
import re

MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
AUDIO_EXT = (".flac", ".mp3", ".wav", ".wma", ".aac", ".m4a", ".ape")

# 明确要删的（非周杰伦原唱 / 翻唱 / 噪音）
DELETE_EXACT = {
    # 非周杰伦
    "蔡琴,童安格 - 纠缠一生",
    "櫻坂46 - Start over!",
    "周杰伦",  # 这是傲艺的翻唱《周杰伦》，不是 Jay 的歌
    # 翻唱（周杰伦在演唱会上翻唱别人的歌）
    "一路上有你+分手总要在雨天",
    "周杰伦X陈慧琳《不如跳舞+Talking+制造浪漫》",
    "山歌好比春江水+多谢了",
    # 噪音（非歌曲）
    "_型男志Men’s JOKER_ 2013年3月封面人物",
    "安徽卫视非常静距离杰伦部分",
    "中国新歌声第二季 第六集 宣传片",
    "逆战特辑 逆境作战",
    "魔术与歌曲：告白气球",
    "欧式风格 展现情歌魅力",
    "周董摇身变欧洲绅士 大跳复古爵士嘻哈舞",
    "M-ZONE 用音乐为奥运加油 饭制版",
    "我永远不会倒下 谁叫我是周杰伦 饭制版",
    "嘻哈小九的完美主义",
    "夜曲电台版 ，梦回2005",
    "上榜单曲 Try",
    "周杰伦的床边故事",  # 这个其实是专辑名文件，可能是整轨或 Intro
    "祝你生日快乐",      # 生日歌翻唱
    "夜上海",            # 经典老歌翻唱
}

# 重复文件：文件名包含这些前缀/后缀的就是重复项（对应干净名已存在时删）
DUP_PATTERNS = [
    (r"^周杰伦\s*\+-\+", ""),      # 周杰伦+-+爱你没差 -> 爱你没差
    (r"^周杰伦\s*-\s*\.", ""),     # 周杰伦 - .比较大的大提琴 -> 比较大的大提琴
    (r"^周杰伦\s*-\s*", ""),       # 周杰伦 - 逆鳞 -> 逆鳞
]


def norm_stem(name: str) -> str:
    s = name
    s = re.sub(r"\s*-\s*周杰伦$", "", s)  # xxx-周杰伦 -> xxx
    for pat, repl in DUP_PATTERNS:
        s = re.sub(pat, repl, s)
    s = s.replace("+", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def main() -> None:
    dry = "--dry" in __import__("sys").argv
    files = [f for f in os.listdir(MUSIC_DIR)
             if os.path.splitext(f)[1].lower() in AUDIO_EXT]
    by_stem: dict[str, list[str]] = {}
    for f in files:
        stem = os.path.splitext(f)[0]
        by_stem.setdefault(stem, []).append(f)

    # 1) 明确删除
    removed, kept = [], []
    for stem, fnames in by_stem.items():
        if stem in DELETE_EXACT:
            removed.extend(fnames)
        else:
            kept.append((stem, fnames))

    # 2) 重复检测：规范化后同名，且原始名更长的删掉
    norm_map: dict[str, list[tuple[str, list[str]]]] = {}
    for stem, fnames in kept:
        n = norm_stem(stem)
        norm_map.setdefault(n, []).append((stem, fnames))

    for n, group in norm_map.items():
        if len(group) > 1:
            # 保留 stem 最短（最干净）的那个
            group.sort(key=lambda x: len(x[0]))
            for stem, fnames in group[1:]:
                removed.extend(fnames)
                print(f"  去重删除: {stem}")

    # 3) 执行
    for f in removed:
        full = os.path.join(MUSIC_DIR, f)
        lrc = os.path.splitext(full)[0] + ".lrc"
        if dry:
            print(f"[DRY] 删除 {f}")
        else:
            try:
                os.unlink(full)
                print(f"删除 {f}")
            except OSError as exc:
                print(f"删除失败 {f}: {exc}")
            if os.path.exists(lrc):
                try:
                    os.unlink(lrc)
                except OSError:
                    pass

    total = len(removed)
    remain = len([f for f in os.listdir(MUSIC_DIR)
                  if os.path.splitext(f)[1].lower() in AUDIO_EXT])
    print(f"\n删除 {total} 个音频，剩余 {remain} 个")
    if dry:
        print("（--dry 模式，未实际删除）")


if __name__ == "__main__":
    main()
