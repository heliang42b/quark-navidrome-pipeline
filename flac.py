# -*- coding: utf-8 -*-
"""flac.music.hi.cn（无损音乐下载）客户端

接口（都是 POST 表单）：
    ajax.php?act=search   platform, keyword, page, size
    ajax.php?act=album    platform, id
    ajax.php?act=playlist platform, id, page, size
    ajax.php?act=getUrl   platform, songid, format, bitrate, time, sign
    ajax.php?act=getLyric platform, songid, time, sign
    kl.php                code（口令解锁）

注意：该站只索引「非版权/免费」曲目——周杰伦原唱全部缺失（实测 14 首 × 2 平台 × 5 页 = 0），
只能搜到翻唱；其它歌手（陈奕迅、林俊杰等）原唱正常。所以拿周杰伦原唱要换源。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

BASE = "https://flac.music.hi.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_cj = CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


class FlacError(RuntimeError):
    pass


def _post(path: str, params: dict, timeout: int = 30) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{BASE}/{path}", data=data, headers={
        "User-Agent": UA, "Referer": BASE + "/", "Origin": BASE,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    raw = _op.open(req, timeout=timeout).read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise FlacError(f"返回不是 JSON：{raw[:120]!r}") from exc


def search(keyword: str, platform: str = "kuwo", page: int = 1, size: int = 20) -> list[dict]:
    res = _post("ajax.php?act=search",
                {"platform": platform, "keyword": keyword, "page": page, "size": size})
    if res.get("code") != 0:
        raise FlacError(res.get("msg") or "搜索失败")
    return (res.get("data") or {}).get("list") or []


def album(album_id: str, platform: str = "kuwo") -> dict:
    res = _post("ajax.php?act=album", {"platform": platform, "id": str(album_id)})
    if res.get("code") != 0:
        raise FlacError(res.get("msg") or "专辑解析失败")
    return res.get("data") or {}


def song_url(song: dict, level: str = "p") -> str:
    """level: p=320k, h=128k。wyy 的 minfo 没有 level 字段，按 codec/bitrate 挑。"""
    minfo = song.get("minfo") or []
    pick = None
    if any("level" in m for m in minfo):
        pick = next((m for m in minfo if m.get("level") == level), None)
    if pick is None:
        mp3s = [m for m in minfo if (m.get("format") or "").lower() == "mp3"]
        pick = (next((m for m in mp3s if str(m.get("bitrate")) == "320"), None)
                or (mp3s[0] if mp3s else (minfo[0] if minfo else None)))
    if not pick:
        raise FlacError("没有可用音质")
    res = _post("ajax.php?act=getUrl", {
        "platform": song.get("platform") or "kuwo", "songid": song["id"],
        "format": pick["format"], "bitrate": pick["bitrate"],
        "time": song["time"], "sign": song["sign"]})
    if res.get("code") != 0:
        raise FlacError(res.get("msg") or "取直链失败")
    return (res.get("data") or {}).get("url") or ""


def lyric(song: dict, platform: str = "kuwo") -> str:
    res = _post("ajax.php?act=getLyric", {"platform": platform, "songid": song["id"],
                                          "time": song["time"], "sign": song["sign"]})
    return res.get("data") or ""


def download(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
    with _op.open(req, timeout=timeout) as resp:
        return resp.read()
