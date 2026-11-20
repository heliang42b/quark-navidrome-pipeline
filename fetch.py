# -*- coding: utf-8 -*-
"""周杰伦原唱批量入库：站点清单(下歌吧) → 歌曲宝核对/取音频 → 打标签 → MUSIC_DIR

节奏与风控：
  * 每首歌之间 5~7s，歌曲宝超过阈值就会抛「请完成人机验证」；
  * 撞到验证就换 cookie 会话 + 退避 120s，同一首最多重试 2 次；
  * 连续 3 首失败整体再歇 300s。

产物：
  data/final_plan.json   核对通过的清单
  data/manifest.jsonl    每首的下载结果（断点续传依据）
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gequbao  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
UA = gequbao.UA

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_TAIL_PAREN = re.compile(r"\s*[\(（\[【][^\(（\[【]*[\)）\]】]\s*$")
_TAIL_DASH = re.compile(r"\s*[\-—–]{1,2}\s*[^\-—–]{1,40}$")

# 非原唱 / 非正式版本标记
BAD_WORDS = [
    "翻唱", "翻自", "cover", "Cover", "COVER", "改编", "致敬", "模仿", "伴奏", "纯音乐",
    "纯享", "inst", "Instrumental", "karaoke", "KTV", "ktv", "DJ", "dj", "Remix", "remix",
    "混音", "串烧", "慢摇", "电音", "8bit", "抖音", "钢琴", "吉他", "古筝", "二胡", "葫芦丝",
    "口琴", "尤克里里", "笛子", "小提琴", "女声", "男声", "童声", "降调", "升调", "变速",
    "加速", "慢速", "铃声", "片段", "搞笑", "恶搞", "现场", "Live", "live", "演唱会",
    "音乐节", "合辑", "精选", "专辑", "无损", "mp3", "MP3", "flac", "FLAC", "wav", "WAV",
    "高音质", "试听", "剪辑", "音乐盒", "八音盒", "轻音乐", "治愈", "睡前", "BGM", "bgm",
    "变调", "消音", "半曲", "副歌", "完整版", "超清", "高清", "经典重现", "歌曲合集",
    "全部歌曲", "作品集", "歌单", "合集", "金曲", "全集", "MV", "花絮", "专访", "采访",
]


def safe_name(name: str, fallback: str = "未命名") -> str:
    name = _BAD.sub("_", (name or "").strip()).strip(" .")
    name = re.sub(r"\s+", " ", name)
    return name[:100] or fallback


def core(title: str) -> str:
    t = (title or "").strip().replace("\u00a0", " ").replace("&nbsp;", " ")
    t = re.sub(r"\.(mp3|flac|wav|m4a|ape|ogg)$", "", t, flags=re.I)
    t = re.sub(r"(?:&|＆|/|、|\+)\s*周杰伦|周杰伦\s*(?:&|＆|/|、|\+)", "", t)
    for _ in range(4):
        t2 = _TAIL_PAREN.sub("", t)
        if t2 == t:
            break
        t = t2
    t2 = _TAIL_DASH.sub("", t)
    if len(t2) >= 2:
        t = t2
    t = re.sub(r"^[\s\-_·]+|[\s\-_·]+$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def key_of(s: str) -> str:
    s = re.sub(r"[\s　]+", "", s or "")
    s = re.sub(r"[·・\.\,\，\。\!\！\?\？\'\"“”‘’\(\)（）\[\]【】《》<>]", "", s)
    return s.lower()


def is_bad(text: str) -> bool:
    return any(w in text for w in BAD_WORDS)


# ------------------------------------------------------------------ 清单

def build_candidates() -> list[dict]:
    rows = json.load(open(os.path.join(DATA, "all.json"), encoding="utf-8"))
    out: dict[str, dict] = {}
    for r in rows:
        artist = (r.get("artist") or "").strip()
        if "周杰伦" not in artist:
            continue
        raw = (r.get("title") or "").strip()
        if not raw or is_bad(raw):
            continue
        c = core(raw)
        if not c or len(c) > 40 or len(c) < 1:
            continue
        k = key_of(c)
        if not k:
            continue
        item = out.setdefault(k, {"core": c, "raw": [], "artists": set()})
        item["raw"].append(raw)
        item["artists"].add(artist)
    for v in out.values():
        v["artists"] = sorted(v["artists"])
    return [out[k] for k in sorted(out)]


# ------------------------------------------------------------------ 取歌

def resolve(cand: dict) -> dict | None:
    """在歌曲宝核对这首歌，返回 info（含下载尝试用的 id 列表）。"""
    c = cand["core"]
    try:
        items = gequbao.search(f"{c} 周杰伦")
    except Exception:  # noqa: BLE001
        return None
    ck = key_of(c)
    ids = []
    for it in items:
        if "周杰伦" not in (it["artist"] or ""):
            continue
        ik = key_of(core(it["title"]))
        if ik != ck and not (len(ck) >= 3 and (ck in ik or ik in ck)):
            continue
        ids.append(it["id"])
    if not ids:
        return None
    return {"core": c, "ids": ids[:3], "site_raw": cand["raw"][:3],
            "site_artists": cand["artists"]}


class Captcha(Exception):
    pass


def fetch_audio(ids: list[str]) -> tuple[dict, bytes] | None:
    last = None
    for sid in ids:
        try:
            info = gequbao.detail(sid)
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
        if str(info.get("type")) not in ("0", "None"):
            continue
        try:
            url = gequbao.play_url(info["playId"], "download")
            data = gequbao.download_bytes(url, retries=2)
            return info, data
        except gequbao.QuotaExceeded as exc:
            raise Captcha(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            if "人机验证" in str(exc):
                raise Captcha(str(exc)) from exc
            last = exc
            time.sleep(1.0)
    if last:
        print(f"      所有条目都失败：{str(last)[:70]}", flush=True)
    return None


def tag(src: str, dst: str, meta: dict, cover: bytes | None) -> None:
    cover_path = None
    if cover:
        if len(cover) > 250_000:
            raw_p, small_p = src + ".cover.raw", src + ".cover.jpg"
            with open(raw_p, "wb") as fh:
                fh.write(cover)
            try:
                subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                                "-i", raw_p, "-vf", "scale=800:-1", "-q:v", "4", small_p],
                               check=True, timeout=60,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                with open(small_p, "rb") as fh:
                    cover = fh.read()
            except Exception:  # noqa: BLE001
                pass
            finally:
                for p in (raw_p, small_p):
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
        extra = ["-metadata:s:v", "title=Album cover",
                 "-metadata:s:v", "comment=Cover (front)"]
    cmd += ["-c", "copy", "-id3v2_version", "3",
            "-metadata", f"title={meta['title']}",
            "-metadata", f"artist={meta['artist']}",
            "-metadata", f"album={meta['album']}",
            "-metadata", f"album_artist={meta.get('album_artist') or meta['artist']}",
            "-metadata", f"comment=来自下歌吧 so.liumingye.cn"]
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


def fetch_cover(url: str) -> bytes | None:
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    cands = build_candidates()
    limit = int(os.environ.get("JAY_LIMIT") or 0)
    if limit:
        cands = cands[:limit]
    print(f"站点候选：{len(cands)} 个歌名", flush=True)

    manifest_path = os.path.join(DATA, "manifest.jsonl")
    resolved_path = os.path.join(DATA, "resolved.json")
    resolved = {}
    if os.path.exists(resolved_path):
        try:
            resolved = json.load(open(resolved_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            resolved = {}
    gap = float(os.environ.get("JAY_GAP") or 30)
    done = {}
    if os.path.exists(manifest_path):
        for line in open(manifest_path, encoding="utf-8"):
            try:
                rec = json.loads(line)
                done[rec.get("core")] = rec
            except Exception:  # noqa: BLE001
                pass

    ok = skip = miss = fail = 0
    streak = 0
    for i, cand in enumerate(cands, 1):
        c = cand["core"]
        target = os.path.join(MUSIC_DIR, f"{safe_name(c)}.mp3")
        if done.get(c, {}).get("ok") or os.path.exists(target):
            skip += 1
            continue

        plan = resolved.get(c)
        if plan:
            pass
        else:
            for attempt in range(3):
                try:
                    plan = resolve(cand)
                    break
                except Captcha as exc:
                    print(f"  [{i}] 人机验证，歇 180s 再来（{exc}）", flush=True)
                    gequbao.reset_session()
                    time.sleep(180)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{i}] 解析异常：{str(exc)[:60]}", flush=True)
                    time.sleep(5)
                    break
            if plan:
                resolved[c] = plan
                try:
                    json.dump(resolved, open(resolved_path, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                except Exception:  # noqa: BLE001
                    pass

        if not plan:
            miss += 1
            with open(manifest_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ok": False, "core": c, "why": "歌曲宝无匹配"},
                                    ensure_ascii=False) + "\n")
            print(f"[{i}/{len(cands)}] MISS {c}", flush=True)
            time.sleep(random.uniform(4, 6))
            continue

        got = None
        for attempt in range(3):
            try:
                got = fetch_audio(plan["ids"])
                break
            except Captcha:
                print(f"  [{i}] {c}: 人机验证，换会话歇 180s", flush=True)
                gequbao.reset_session()
                time.sleep(180 + random.uniform(0, 30))
        if not got:
            fail += 1
            streak += 1
            with open(manifest_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ok": False, "core": c, "why": "取音频失败"},
                                    ensure_ascii=False) + "\n")
            print(f"[{i}/{len(cands)}] FAIL {c}", flush=True)
            if streak >= 3:
                print("  连续失败，整体歇 300s", flush=True)
                gequbao.reset_session()
                time.sleep(300)
                streak = 0
            continue

        info, data = got
        tmp = os.path.join(MUSIC_DIR, f".tmp_{i}.mp3")
        with open(tmp, "wb") as fh:
            fh.write(data)
        title = c
        artist = (info.get("artist") or "周杰伦").strip()
        meta = {
            "title": title,
            "artist": artist if "周杰伦" in artist else "周杰伦",
            "album": "周杰伦",
            "album_artist": "周杰伦",
        }
        tag(tmp, target, meta, fetch_cover(info.get("cover") or ""))
        try:
            os.unlink(tmp)
        except OSError:
            pass
        lrc = (info.get("lyrics") or "").strip()
        if lrc:
            with open(os.path.splitext(target)[0] + ".lrc", "w", encoding="utf-8") as fh:
                fh.write(lrc if lrc.endswith("\n") else lrc + "\n")
        ok += 1
        streak = 0
        rec = {"ok": True, "core": c, "bytes": len(data), "sid": info.get("id"),
               "lrc": bool(lrc), "cover": bool(info.get("cover"))}
        with open(manifest_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(cands)}] OK   {c}  {len(data)//1024}KB"
              f"{' +lrc' if lrc else ''}", flush=True)
        time.sleep(gap + random.uniform(0, 8))

    print(f"\n完成：新增 {ok}，已存在跳过 {skip}，无匹配 {miss}，失败 {fail}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
