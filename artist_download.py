# -*- coding: utf-8 -*-
"""通用：按 final 清单下载歌手 FLAC → 打标签 → os.environ.get("MUSIC_ROOT")/<歌手>。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flac  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ARTIST = sys.argv[1] if len(sys.argv) > 1 else "林忆莲"
FINAL = sys.argv[2] if len(sys.argv) > 2 else f"{ARTIST}_final.json"
MUSIC_DIR = os.path.join(os.environ.get("MUSIC_ROOT", os.path.join(os.path.expanduser("~"), "Music")), ARTIST)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
UA = flac.UA
_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(n):
    n = _BAD.sub("_", (n or "").strip()).strip(" .")
    return re.sub(r"\s+", " ", n)[:100] or "未命名"


def norm(s):
    return re.sub(r"[\s　·・\.\,\，。\'\"]", "", s or "").lower()


def resolve_fresh(title: str) -> dict | None:
    for kw in (f"{title} {ARTIST}", title):
        try:
            rows = flac.search(kw, platform="kuwo", page=1, size=40)
        except Exception:  # noqa: BLE001
            continue
        best = None
        for r in rows:
            name = (r.get("name") or r.get("title") or "").strip()
            a = (r.get("artist") or "").strip()
            if ARTIST not in a:
                continue
            nk = norm(name)
            tk = norm(title)
            if nk == tk or (len(tk) >= 2 and (tk in nk or nk in tk)):
                has_flac = any(m.get("format") == "flac" or m.get("level") == "ff"
                               for m in (r.get("minfo") or []))
                score = 1 if has_flac else 0
                if best is None or score > best[0]:
                    best = (score, r)
        if best:
            r = best[1]
            r["name"] = (r.get("name") or r.get("title") or "").strip()
            return r
    return None


def try_download(song: dict, minfo: list) -> tuple[bytes, str] | None:
    for m in minfo:
        try:
            res = flac._post("ajax.php?act=getUrl", {
                "platform": "kuwo", "songid": str(song["id"]),
                "format": m["format"], "bitrate": m["bitrate"],
                "time": str(song.get("time")), "sign": song.get("sign")})
            if res.get("code") != 0:
                continue
            url = (res.get("data") or {}).get("url") or ""
            if not url:
                continue
            data = flac.download(url)
            if len(data) > 300 * 1024:
                return data, m["format"]
        except Exception:  # noqa: BLE001
            continue
    return None


def tag(src, dst, meta, cover=None):
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
                               check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
        cmd += ["-i", cover_path, "-map", "0:a", "-map", "1:v"]
        extra = ["-disposition:v", "attached_pic", "-metadata:s:v", "title=Album cover",
                 "-metadata:s:v", "comment=Cover (front)"]
    cmd += ["-c", "copy", "-metadata", f"title={meta['title']}",
            "-metadata", f"artist={ARTIST}", "-metadata", f"album={meta['album']}",
            "-metadata", f"album_artist={ARTIST}", "-metadata", "comment=来自 flac.music.hi.cn"]
    cmd += extra + [dst]
    try:
        subprocess.run(cmd, check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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


def fetch_cover(url):
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    plan = json.load(open(os.path.join(DATA, FINAL), encoding="utf-8"))
    print(f"清单 {len(plan)} 首 -> {MUSIC_DIR}", flush=True)

    manifest = os.path.join(DATA, f"{ARTIST}_manifest.jsonl")
    done = set()
    if os.path.exists(manifest):
        for line in open(manifest, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("ok"):
                    done.add(r["title"])
            except Exception:  # noqa: BLE001
                pass

    ok = skip = fail = 0
    for i, p in enumerate(plan, 1):
        title = p["title"]
        base = safe_name(title)
        if os.path.exists(os.path.join(MUSIC_DIR, base + ".flac")) or os.path.exists(
                os.path.join(MUSIC_DIR, base + ".mp3")):
            skip += 1
            continue
        if title in done:
            skip += 1
            continue
        try:
            song = resolve_fresh(title)
            if not song:
                raise RuntimeError("搜索无匹配")
            minfo = song.get("minfo") or []
            ordered = sorted(minfo, key=lambda m: (m.get("format") != "flac", m.get("format") != "mp3",
                                                    -int(m.get("bitrate") or 0)))
            got = try_download(song, ordered)
            if not got:
                raise RuntimeError("下载失败")
            data, fmt = got
            ext = f".{fmt}" if fmt in ("flac", "mp3", "wav") else ".mp3"
            dst = os.path.join(MUSIC_DIR, base + ext)
            tmp = dst + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            album = (p.get("album") or ARTIST).strip()
            tag(tmp, dst, {"title": title, "album": album},
                fetch_cover(song.get("pic_url") or p.get("pic") or ""))
            try:
                os.unlink(tmp)
            except OSError:
                pass
            ok += 1
            rec = {"ok": True, "title": title, "bytes": len(data), "format": fmt, "album": album}
            print(f"[{i}/{len(plan)}] OK   {title}  {len(data)//1024}KB {fmt}", flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            rec = {"ok": False, "title": title, "err": str(exc)[:150]}
            print(f"[{i}/{len(plan)}] FAIL {title}  {str(exc)[:90]}", flush=True)
        with open(manifest, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        time.sleep(0.5)

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}", flush=True)


if __name__ == "__main__":
    main()
