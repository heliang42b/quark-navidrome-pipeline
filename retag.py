# -*- coding: utf-8 -*-
"""收尾：用酷狗搜索补全专辑名/音轨号（酷我-酷狗免费接口，免登录），只改标签不动音频流。

用法：
    python retag.py            # 扫描 MUSIC_DIR 下所有音频
    python retag.py --dry      # 只看匹配结果不改文件
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kugou_meta.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
AUDIO_EXT = (".flac", ".mp3", ".wav", ".ape", ".m4a")


def kugou_search(title: str) -> list[dict]:
    q = urllib.parse.quote(f"{title} 周杰伦")
    url = f"http://mobilecdn.kugou.com/api/v3/search/song?format=json&keyword={q}&page=1&pagesize=8"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.kugou.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return ((d.get("data") or {}).get("info")) or []


def norm(s: str) -> str:
    return re.sub(r"[\s　·・\.\,\，\。\!\！\?\？\'\"“”‘’\(\)（）\[\]【】《》<>]", "", s or "").lower()


def probe(path: str) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_format", path],
                         capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    tags = {}
    for line in out.splitlines():
        m = re.match(r"TAG:(title|artist|album|album_artist|track)=(.*)", line.strip())
        if m:
            tags[m.group(1)] = m.group(2).strip()
    return tags


def retag(path: str, title: str, artist: str, album: str, track: str = "") -> bool:
    tmp = path + ".retag" + os.path.splitext(path)[1]
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-c", "copy",
           "-metadata", f"title={title}", "-metadata", f"artist={artist}",
           "-metadata", f"album={album}", "-metadata", f"album_artist=周杰伦"]
    if track:
        cmd += ["-metadata", f"track={track}"]
    cmd += [tmp]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def main() -> None:
    dry = "--dry" in sys.argv
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(AUDIO_EXT)]
    print(f"待处理 {len(files)} 个音频文件", flush=True)
    fixed = skipped = 0
    for i, name in enumerate(sorted(files), 1):
        path = os.path.join(MUSIC_DIR, name)
        tags = probe(path)
        title = tags.get("title") or os.path.splitext(name)[0]
        if title in cache:
            meta = cache[title]
        else:
            meta = None
            try:
                rows = kugou_search(title)
            except Exception as exc:  # noqa: BLE001
                print(f"  {title}: 查询失败 {str(exc)[:50]}", flush=True)
                rows = []
            for it in rows:
                if "周杰伦" not in (it.get("singername") or ""):
                    continue
                if norm(it.get("songname") or "") != norm(title):
                    continue
                meta = {"album": (it.get("album_name") or "").strip(),
                        "track": str(it.get("track") or ""),
                        "artist_cn": (it.get("singername") or "").strip()}
                break
            cache[title] = meta
            time.sleep(0.35)

        album = (meta or {}).get("album") or tags.get("album") or "周杰伦"
        track = (meta or {}).get("track") or ""
        artist = tags.get("artist") or "周杰伦"
        if dry:
            print(f"[{i}] {title}: album={album!r} track={track}", flush=True)
            continue
        if album == tags.get("album") and (not track or track == tags.get("track")):
            skipped += 1
            continue
        ok = retag(path, title, artist, album, track)
        if ok:
            fixed += 1
            print(f"[{i}] {title} -> {album} #{track}", flush=True)
        else:
            print(f"[{i}] {title} 写标签失败", flush=True)
        if i % 25 == 0:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成：改写 {fixed}，无需改动 {skipped}", flush=True)


if __name__ == "__main__":
    main()
