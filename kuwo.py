# -*- coding: utf-8 -*-
"""酷我 (kuwo.cn) 备用源客户端：搜索 / 取直链 / 下载。

gequbao 的音频本来就来自酷我 CDN，所以同一批歌可以在这里拿。
只依赖标准库。
"""
from __future__ import annotations

import ast
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

NON_ORIGINAL = ("翻唱", "cover", "Cover", "COVER", "伴奏", "纯音乐", "karaoke", "Karaoke",
                "DJ版", "dj版", "DJ ", "Remix", "remix", "混音", "串烧", "钢琴版", "吉他版",
                "抖音", "女声版", "男声版", "童声", "降调", "升调", "铃声", "纯享",
                "KTV", "ktv", "片段", "搞笑版", "现场版", "Live", "live")


class KuwoError(RuntimeError):
    pass


def _get(url: str, headers: dict | None = None, timeout: int = 25) -> bytes:
    h = {"User-Agent": UA, "Referer": "https://www.kuwo.cn/"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text: str) -> str:
    return (text or "").replace("&nbsp;", " ").replace("\u00a0", " ").strip()


def search(keyword: str, pn: int = 0, rn: int = 30) -> list[dict]:
    """老版接口返回的是 Python 字面量串，用 ast 解析最稳。"""
    url = ("http://search.kuwo.cn/r.s?all=%s&ft=music&itemset=web_2013&client=kt"
           "&pn=%d&rn=%d&rformat=json&encoding=utf8" % (urllib.parse.quote(keyword), pn, rn))
    raw = _get(url).decode("utf-8", "replace")
    try:
        data = ast.literal_eval(raw)
    except Exception:  # noqa: BLE001
        try:
            data = json.loads(raw.replace("'", '"'))
        except Exception as exc:  # noqa: BLE001
            raise KuwoError(f"搜索结果解析失败：{raw[:80]!r}") from exc
    rows = data.get("abslist") or []
    out = []
    for it in rows:
        rid = str(it.get("MUSICRID") or "").replace("MUSIC_", "")
        if not rid:
            continue
        out.append({
            "id": rid,
            "title": _clean(it.get("NAME") or it.get("SONGNAME") or ""),
            "fullTitle": _clean(it.get("SONGNAME") or ""),
            "artist": _clean(it.get("ARTIST") or ""),
            "album": _clean(it.get("ALBUM") or ""),
            "duration": int(float(it.get("DURATION") or 0)),
            "cover": ("https://img1.kuwo.cn/star/albumcover/" + it["web_albumpic_short"].lstrip("/")
                      if it.get("web_albumpic_short") else ""),
        })
    return out


def is_original(it: dict, name: str) -> bool:
    if name not in (it["artist"] or ""):
        return False
    blob = f"{it['fullTitle']} {it['artist']}"
    return not any(h in blob for h in NON_ORIGINAL)


def play_url(rid: str, br: str = "128kmp3") -> str:
    url = ("https://antiserver.kuwo.cn/anti.s?type=convert_url3&rid=MUSIC_%s&format=mp3&br=%s"
           % (urllib.parse.quote(str(rid)), br))
    raw = _get(url, {"Referer": "https://www.kuwo.cn/"}).decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise KuwoError(f"取直链返回异常：{raw[:80]}") from exc
    if payload.get("code") != 200 or not payload.get("url"):
        raise KuwoError(f"取直链失败：{payload.get('msg') or payload}")
    return payload["url"]


def download_bytes(url: str, retries: int = 2) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            data = _get(url, {"Referer": "https://www.kuwo.cn/"}, timeout=120)
            if len(data) < 4096:
                raise KuwoError("下载内容过小")
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (attempt + 1))
    raise KuwoError(f"音频下载失败：{last}")


def fetch_song(rid: str, title: str = "", artist: str = "") -> tuple[dict, bytes]:
    url = play_url(rid)
    audio = download_bytes(url)
    return {
        "id": rid,
        "title": title,
        "artist": artist,
        "cover": "",
        "lyrics": "",
    }, audio
