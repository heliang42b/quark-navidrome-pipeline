# -*- coding: utf-8 -*-
"""阶段二：按 plan_unique.json 下载 320k mp3 → 打标签 → 放进 Navidrome 曲库。

- 音频：酷我 320k mp3 直链
- 标签：title / artist / album / album_artist
- 封面：酷我专辑图（大于 250KB 先压到 800px）
- 歌词：lrclib 同步歌词 → 同名 .lrc；拿不到就跳过
- 断点续传：目标文件已存在则跳过
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kuwo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
UA = kuwo.UA

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(name: str, fallback: str = "未命名") -> str:
    name = _BAD.sub("_", (name or "").strip()).strip(" .")
    name = re.sub(r"\s+", " ", name)
    return name[:100] or fallback


def get(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def fetch_cover(url: str) -> bytes | None:
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    try:
        return get(url, {"Referer": "https://www.kuwo.cn/"}, timeout=30)
    except Exception:  # noqa: BLE001
        return None


def fetch_lrc(title: str, artist: str, duration: int) -> str:
    """lrclib：优先同步歌词。"""
    bases = ["https://lrclib.net/api/get", "https://lrclib.net/api/search"]
    q = urllib.parse.urlencode({
        "artist_name": "周杰伦",
        "track_name": title,
        "album_name": "",
        "duration": str(duration or ""),
    })
    try:
        d = json.loads(get(f"{bases[0]}?{q}", {"User-Agent": "quark-navidrome/1.0"}, 25).decode("utf-8"))
        lrc = d.get("syncedLyrics") or ""
        if lrc.strip():
            return lrc
    except Exception:  # noqa: BLE001
        pass
    try:
        q2 = urllib.parse.urlencode({"q": f"{title} 周杰伦"})
        arr = json.loads(get(f"{bases[1]}?{q2}", {"User-Agent": "quark-navidrome/1.0"}, 25).decode("utf-8"))
        for item in arr or []:
            if "周杰伦" not in (item.get("artistName") or ""):
                continue
            lrc = item.get("syncedLyrics") or ""
            if lrc.strip():
                return lrc
    except Exception:  # noqa: BLE001
        pass
    return ""


def tag(src: str, dst: str, meta: dict, cover: bytes | None) -> None:
    cover_path = None
    if cover:
        if len(cover) > 250_000:
            raw = src + ".cover.raw"
            small = src + ".cover.jpg"
            with open(raw, "wb") as fh:
                fh.write(cover)
            try:
                subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                                "-i", raw, "-vf", "scale=800:-1", "-q:v", "4", small],
                               check=True, timeout=60,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                with open(small, "rb") as fh:
                    cover = fh.read()
            except Exception:  # noqa: BLE001
                pass
            finally:
                for p in (raw, small):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
        cover_path = src + ".cover.jpg"
        with open(cover_path, "wb") as fh:
            fh.write(cover)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    extra = []
    if cover_path:
        cmd += ["-i", cover_path]
        cmd += ["-map", "0:a", "-map", "1:v"]
        extra = ["-metadata:s:v", "title=Album cover",
                 "-metadata:s:v", "comment=Cover (front)"]
    cmd += ["-c", "copy", "-id3v2_version", "3",
            "-metadata", f"title={meta['title']}",
            "-metadata", f"artist={meta['artist']}",
            "-metadata", f"album={meta['album']}",
            "-metadata", f"album_artist={meta.get('album_artist') or meta['artist']}",
            "-metadata", f"comment=来自下歌吧 so.liumingye.cn · {meta.get('rid', '')}"]
    cmd += extra + [dst]
    try:
        subprocess.run(cmd, check=True, timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception:  # noqa: BLE001
        if os.path.exists(dst):
            os.unlink(dst)
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            fo.write(fi.read())
    finally:
        if cover_path:
            try:
                os.unlink(cover_path)
            except OSError:
                pass


def main() -> None:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    plan = json.load(open(os.path.join(DATA, "plan_unique.json"), encoding="utf-8"))
    print(f"清单 {len(plan)} 首", flush=True)

    manifest_path = os.path.join(DATA, "manifest.jsonl")
    done = set()
    if os.path.exists(manifest_path):
        for line in open(manifest_path, encoding="utf-8"):
            try:
                rec = json.loads(line)
                if rec.get("ok"):
                    done.add(str(rec.get("rid")))
            except Exception:  # noqa: BLE001
                pass

    ok = skip = fail = 0
    for i, item in enumerate(plan, 1):
        rid = str(item["rid"])
        title = safe_name(item["core"])
        target = os.path.join(MUSIC_DIR, f"{title}.mp3")
        if rid in done or os.path.exists(target):
            skip += 1
            continue
        tmp = os.path.join(MUSIC_DIR, f".tmp_{rid}.mp3")
        try:
            audio = None
            for br in ("320kmp3", "192kmp3", "128kmp3"):
                try:
                    url = kuwo.play_url(rid, br)
                    data = kuwo.download_bytes(url)
                    if len(data) > 1024 * 100:
                        audio = data
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not audio:
                raise RuntimeError("直链全部失败")
            with open(tmp, "wb") as fh:
                fh.write(audio)
            cover = fetch_cover(item.get("cover") or "")
            meta = {
                "title": item["core"],
                "artist": item.get("artist") or "周杰伦",
                "album": item.get("album") or "周杰伦",
                "album_artist": "周杰伦",
                "rid": rid,
            }
            tag(tmp, target, meta, cover)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            lrc = fetch_lrc(item["core"], "周杰伦", item.get("duration") or 0)
            if lrc.strip():
                with open(os.path.splitext(target)[0] + ".lrc", "w", encoding="utf-8") as fh:
                    fh.write(lrc)
            ok += 1
            rec = {"ok": True, "rid": rid, "title": item["core"], "album": meta["album"],
                   "bytes": len(audio), "lrc": bool(lrc.strip())}
            print(f"[{i}/{len(plan)}] OK  {item['core']}  ({len(audio)//1024}KB)"
                  f"{' +lrc' if lrc.strip() else ''}", flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            rec = {"ok": False, "rid": rid, "title": item["core"], "err": str(exc)}
            print(f"[{i}/{len(plan)}] FAIL {item['core']}  {exc}", flush=True)
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        with open(manifest_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        time.sleep(0.25)

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
