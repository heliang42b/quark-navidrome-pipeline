# -*- coding: utf-8 -*-
"""阶段 B（需要夸克登录态）：把站点给的夸克分享逐个转存 → 取直链 → 下载 → 打标签入库。

用法：
    python quark_dl.py --test "https://pan.quark.cn/s/xxxxxxxx"    # 只跑一个分享，验证登录态
    python quark_dl.py                                            # 跑 shares.json 全量

Cookie 放在 data/quark_cookie.txt（就是浏览器里 pan.quark.cn 的 Cookie 整行）。
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
BASE = "https://drive-pc.quark.cn/1/clouddrive"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
COOKIE_PATH = os.path.join(DATA, "quark_cookie.txt")

AUDIO_EXT = (".mp3", ".flac", ".wav", ".ape", ".m4a", ".aac", ".ogg", ".wma")
ZIP_EXT = (".zip", ".rar", ".7z")
_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def cookie() -> str:
    return open(COOKIE_PATH, encoding="utf-8").read().strip()


def safe_name(name: str, fallback: str = "未命名") -> str:
    name = _BAD.sub("_", (name or "").strip()).strip(" .")
    name = re.sub(r"\s+", " ", name)
    return name[:110] or fallback


def api(path: str, payload=None, method="POST", params=None, timeout=30):
    q = {"pr": "ucpro", "fr": "pc"}
    if params:
        q.update(params)
    url = f"{BASE}/{path}?{urllib.parse.urlencode(q)}"
    headers = {
        "User-Agent": UA,
        "Cookie": cookie(),
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://pan.quark.cn/",
        "Origin": "https://pan.quark.cn",
        "Accept": "application/json, text/plain, */*",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        body = ""
        if hasattr(exc, "read"):
            body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{path}: {exc} {body}") from exc


def parse_share(url: str) -> tuple[str, str]:
    m = re.search(r"pan\.quark\.cn/s/([0-9a-zA-Z]+)", url)
    if not m:
        raise ValueError(f"不是夸克分享链接：{url}")
    pwd_id = m.group(1)
    q = urllib.parse.urlparse(url).query
    passcode = ""
    if q:
        params = urllib.parse.parse_qs(q)
        passcode = (params.get("pwd") or params.get("passcode") or [""])[0]
    return pwd_id, passcode


def share_files(pwd_id: str, passcode: str) -> tuple[str, list[dict]]:
    tok = api("share/sharepage/token", {"pwd_id": pwd_id, "passcode": passcode})
    stoken = ((tok.get("data") or {}).get("stoken")) or ""
    if not stoken:
        raise RuntimeError(f"拿不到 stoken：{json.dumps(tok, ensure_ascii=False)[:200]}")
    det = api("share/sharepage/detail", method="GET", params={
        "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": "0", "force": "0",
        "_page": "1", "_size": "200", "_fetch_banner": "0",
        "_fetch_share": "1", "_fetch_total": "1"})
    lst = ((det.get("data") or {}).get("list")) or []
    return stoken, lst


def save_and_wait(pwd_id: str, stoken: str, files: list[dict]) -> list[dict]:
    payload = {
        "fid_list": [f["fid"] for f in files],
        "fid_token_list": [f["share_fid_token"] for f in files],
        "to_pdir_fid": "0",
        "pwd_id": pwd_id,
        "stoken": stoken,
        "pdir_fid": "0",
        "scene": "link",
    }
    res = api("share/sharepage/save", payload)
    task_id = ((res.get("data") or {}).get("task_id")) or ""
    if not task_id:
        raise RuntimeError(f"转存失败：{json.dumps(res, ensure_ascii=False)[:200]}")
    for _ in range(30):
        time.sleep(1.0)
        t = api("task", method="GET", params={"task_id": task_id, "retry_index": "0"})
        d = t.get("data") or {}
        if str(d.get("status")) == "2":
            return ((d.get("save_as") or {}).get("save_as_top_fids")) or []
        if d.get("status") not in (0, 1, None):
            raise RuntimeError(f"转存任务异常：{json.dumps(d, ensure_ascii=False)[:200]}")
    raise RuntimeError("转存超时")


def download_urls(fids: list[str]) -> dict[str, str]:
    """转存后立刻取直链；刚转存完偶尔会 404，重试几次。"""
    last = None
    for attempt in range(6):
        try:
            res = api("file/download", {"fids": fids})
            out = {}
            for item in (res.get("data") or []):
                fid = item.get("fid")
                url = item.get("download_url")
                if fid and url:
                    out[fid] = url
            if out:
                return out
            last = "直链为空"
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1.5 * (attempt + 1))
    if last:
        raise RuntimeError(f"取直链失败：{str(last)[:120]}")
    return {}


def fetch(url: str, timeout=300) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cookie": cookie(),
        "Referer": "https://pan.quark.cn/", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def delete_files(fids: list[str]) -> None:
    try:
        api("file/delete", {"action_type": 2, "filelist": fids, "exclude_fids": []})
    except Exception:  # noqa: BLE001
        pass


def root_fids() -> set[str]:
    try:
        r = api("file/sort", method="GET", params={
            "pdir_fid": "0", "_page": "1", "_size": "200", "_fetch_total": "1"})
        return {f["fid"] for f in ((r.get("data") or {}).get("list") or [])}
    except Exception:  # noqa: BLE001
        return set()


def lrclib(title: str, duration: int = 0) -> tuple[str, str]:
    """返回 (album, 同步歌词)。lrclib 对华语歌质量还行，拿不到就空着。"""
    q = urllib.parse.urlencode({"artist_name": "周杰伦", "track_name": title,
                                "album_name": "", "duration": str(duration or "")})
    try:
        req = urllib.request.Request(f"https://lrclib.net/api/get?{q}",
                                     headers={"User-Agent": "quark-navidrome/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return (d.get("albumName") or "").strip(), (d.get("syncedLyrics") or "").strip()
    except Exception:  # noqa: BLE001
        return "", ""


# ---------------------------------------------------------------- 入库

def tag(src: str, dst: str, meta: dict, cover: bytes | None) -> None:
    cover_path = None
    if cover:
        cp = src + ".cover.jpg"
        with open(cp, "wb") as fh:
            fh.write(cover)
        cover_path = cp
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    extra = []
    if cover_path:
        cmd += ["-i", cover_path, "-map", "0:a", "-map", "1:v"]
        extra = ["-disposition:v", "attached_pic",
                 "-metadata:s:v", "title=Album cover",
                 "-metadata:s:v", "comment=Cover (front)"]
    cmd += ["-c", "copy",
            "-metadata", f"title={meta['title']}",
            "-metadata", f"artist={meta['artist']}",
            "-metadata", f"album={meta['album']}",
            "-metadata", f"album_artist={meta.get('album_artist') or meta['artist']}",
            "-metadata", f"comment=来自下歌吧 so.liumingye.cn"]
    cmd += extra + [dst]
    try:
        subprocess.run(cmd, check=True, timeout=300,
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


def lrc_from_site(lyrics: str) -> str:
    if not lyrics:
        return ""
    text = lyrics.strip()
    # 站点给的是纯文本（首行是「歌名 - 歌手」），换成无时间轴的文本歌词
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and " - " in lines[0]:
        lines = lines[1:]
    return "\n".join(lines)


def walk_audio(pwd_id: str, stoken: str, pdir: str = "0", depth: int = 0) -> list[dict]:
    """分享里是文件夹时，递归把音频文件找出来。"""
    if depth > 3:
        return []
    det = api("share/sharepage/detail", method="GET", params={
        "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": pdir, "force": "0",
        "_page": "1", "_size": "200", "_fetch_banner": "0",
        "_fetch_share": "1", "_fetch_total": "1"})
    out = []
    for f in ((det.get("data") or {}).get("list")) or []:
        name = f.get("file_name") or ""
        if f.get("dir") or f.get("file_type") == 0:
            out.extend(walk_audio(pwd_id, stoken, f["fid"], depth + 1))
        elif name.lower().endswith(AUDIO_EXT):
            f["file_name"] = name
            out.append(f)
    return out


def handle_song(item: dict, dry: bool = False) -> dict:
    url = item["url"]
    pwd_id, passcode = parse_share(url)
    stoken, files = share_files(pwd_id, passcode)
    audios = [f for f in files if (f.get("file_name") or "").lower().endswith(AUDIO_EXT)]
    if not audios:
        audios = walk_audio(pwd_id, stoken)
    if not audios:
        return {"ok": False, "why": f"分享里没有音频（{len(files)} 个文件）"}

    if dry:
        return {"ok": True, "dry": True,
                "files": [(f["file_name"], f.get("size")) for f in audios]}

    before = root_fids()
    saved = save_and_wait(pwd_id, stoken, audios)
    if not saved:
        return {"ok": False, "why": "转存后没有返回文件"}

    written = []
    try:
        urls = download_urls(saved)
        if not urls:
            return {"ok": False, "why": "拿不到下载直链"}

        album, synced = lrclib(item["core"])
        for idx, fid in enumerate(saved):
            url2 = urls.get(fid)
            if not url2:
                continue
            data = fetch(url2)
            if len(data) < 64 * 1024:
                continue
            # 多轨分享（整张专辑）用原文件名，单曲用站点歌名
            if len(saved) == 1:
                base, title = safe_name(item["core"]), item["core"]
            else:
                raw_name = audios[idx]["file_name"] if idx < len(audios) else item["core"]
                stem = os.path.splitext(raw_name)[0]
                stem = re.sub(r"^\s*\d{1,2}[\s\.\-_、]+", "", stem).strip()
                title = stem or item["core"]
                base = safe_name(title)
            ext = os.path.splitext(audios[idx]["file_name"] if idx < len(audios) else "")[1].lower()
            if ext not in AUDIO_EXT:
                ext = ".flac" if data[:4] == b"fLaC" else ".mp3"
            dst = os.path.join(MUSIC_DIR, base + ext)
            tmp = dst + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            # 同名旧版本（早先抓的 128k mp3）删掉，避免曲库重复
            for old in (".mp3", ".flac", ".wav"):
                op = os.path.join(MUSIC_DIR, base + old)
                if old != ext and os.path.exists(op):
                    try:
                        os.unlink(op)
                        lp = os.path.splitext(op)[0] + ".lrc"
                        if os.path.exists(lp):
                            os.unlink(lp)
                    except OSError:
                        pass
            meta = {"title": title, "artist": item.get("artist") or "周杰伦",
                    "album": album or "周杰伦", "album_artist": "周杰伦"}
            tag(tmp, dst, meta, fetch_cover(item.get("cover") or ""))
            try:
                os.unlink(tmp)
            except OSError:
                pass
            lrc = synced or lrc_from_site(item.get("lyrics") or "")
            if lrc:
                with open(os.path.splitext(dst)[0] + ".lrc", "w", encoding="utf-8") as fh:
                    fh.write(lrc if lrc.endswith("\n") else lrc + "\n")
            written.append((dst, len(data)))
            if len(written) >= 1 and len(saved) == 1:
                break
    finally:
        # 只删自己转存的文件，别碰别人的（多线程时不会互相删）
        try:
            if saved:
                delete_files(saved)
        except Exception:  # noqa: BLE001
            pass

    if not written:
        return {"ok": False, "why": "下载内容为空"}
    return {"ok": True, "path": written[0][0], "bytes": written[0][1], "tracks": len(written)}


def main() -> None:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    if not os.path.exists(COOKIE_PATH):
        print(f"缺 {COOKIE_PATH}", flush=True)
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        title = sys.argv[3] if len(sys.argv) > 3 else "test"
        r = handle_song({"core": title, "url": sys.argv[2]}, dry="--dry" in sys.argv)
        print(json.dumps(r, ensure_ascii=False, indent=1)[:800])
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--clean":
        left = sorted(root_fids())
        if left:
            delete_files(left)
        print(f"清理了 {len(left)} 个网盘残留")
        return

    shares = json.load(open(os.path.join(DATA, "shares.json"), encoding="utf-8"))
    manifest = os.path.join(DATA, "quark_manifest.jsonl")
    done = set()
    if os.path.exists(manifest):
        for line in open(manifest, encoding="utf-8"):
            try:
                rec = json.loads(line)
                if rec.get("ok"):
                    done.add(rec.get("core"))
            except Exception:  # noqa: BLE001
                pass

    items = [v for v in shares.values()]
    print(f"待处理 {len(items)} 首（已完成 {len(done)}）", flush=True)

    from concurrent.futures import ThreadPoolExecutor
    import threading
    lock = threading.Lock()
    stat = {"ok": 0, "skip": 0, "fail": 0, "i": 0}

    def work(it: dict) -> None:
        with lock:
            stat["i"] += 1
            idx = stat["i"]
        if it["core"] in done:
            with lock:
                stat["skip"] += 1
            return
        try:
            r = handle_song(it)
        except Exception:  # noqa: BLE001
            time.sleep(2)
            try:
                r = handle_song(it)
            except Exception as exc2:  # noqa: BLE001
                r = {"ok": False, "why": str(exc2)[:160]}
        rec = {"core": it["core"], **r}
        with lock:
            with open(manifest, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if r.get("ok"):
                stat["ok"] += 1
                print(f"[{idx}/{len(items)}] OK   {it['core']}  {r.get('bytes', 0)//1024}KB "
                      f"({it.get('quality')})", flush=True)
            else:
                stat["fail"] += 1
                print(f"[{idx}/{len(items)}] FAIL {it['core']}  {r.get('why')}", flush=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(work, items))
    print(f"\n完成：成功 {stat['ok']}，跳过 {stat['skip']}，失败 {stat['fail']}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
