# -*- coding: utf-8 -*-
"""抢救失败项：
  1) .wma / 404 的直接重试（下载进库）
  2) 专辑 zip：下载 → 本地解压 → 音频入库
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quark_dl as Q

MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
MANIFEST = os.path.join(Q.DATA, "quark_manifest.jsonl")
SHARES = os.path.join(Q.DATA, "shares.json")


def load_fails() -> dict:
    shares = json.load(open(SHARES, encoding="utf-8"))
    by_core = {v["core"]: v for v in shares.values()}
    fails = {}
    for line in open(MANIFEST, encoding="utf-8"):
        r = json.loads(line)
        if not r.get("ok"):
            fails[r["core"]] = r  # 最后一次结果
    return fails, by_core


def download_to_tmp(pwd_id, stoken, f) -> bytes:
    saved = Q.save_and_wait(pwd_id, stoken, [f])
    if not saved:
        raise RuntimeError("转存失败")
    urls = Q.download_urls(saved)
    if not urls:
        raise RuntimeError("无直链")
    data = Q.fetch(list(urls.values())[0])
    Q.delete_files(saved)
    return data


def import_audio(data: bytes, name: str, core: str, ext: str) -> str:
    base = Q.safe_name(core)
    dst = os.path.join(MUSIC_DIR, base + ext)
    tmp = dst + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    Q.tag(tmp, dst, {"title": core, "artist": "周杰伦", "album": "周杰伦",
                     "album_artist": "周杰伦"}, None)
    os.unlink(tmp)
    return dst


def handle_wma_404(it, core, r) -> bool:
    url = it.get("url") or ""
    if "pan.quark.cn" not in url:
        return False
    pwd_id, passcode = Q.parse_share(url)
    stoken, files = Q.share_files(pwd_id, passcode)
    audios = [f for f in files if (f.get("file_name") or "").lower().endswith(Q.AUDIO_EXT)]
    if not audios:
        audios = Q.walk_audio(pwd_id, stoken)
    if not audios:
        return False
    f = audios[0]
    data = download_to_tmp(pwd_id, stoken, f)
    ext = os.path.splitext(f["file_name"])[1].lower()
    import_audio(data, f["file_name"], core, ext)
    print(f"OK  {core}  ({ext})", flush=True)
    return True


def handle_zip(it, core) -> bool:
    url = it.get("url") or ""
    if "pan.quark.cn" not in url:
        return False
    pwd_id, passcode = Q.parse_share(url)
    stoken, files = Q.share_files(pwd_id, passcode)

    zips = []
    for f in files:
        name = (f.get("file_name") or "").lower()
        if name.endswith(Q.ZIP_EXT):
            zips.append(f)
    # 目录里找 zip
    if not zips:
        # 递归找
        def find_zip(pdir, depth=0):
            if depth > 2:
                return []
            det = Q.api("share/sharepage/detail", method="GET", params={
                "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": pdir, "force": "0",
                "_page": "1", "_size": "100", "_fetch_banner": "0", "_fetch_share": "1", "_fetch_total": "1"})
            out = []
            for f in ((det.get("data") or {}).get("list")) or []:
                nm = f.get("file_name") or ""
                if f.get("dir") or f.get("file_type") == 0:
                    out.extend(find_zip(f["fid"], depth + 1))
                elif nm.lower().endswith(Q.ZIP_EXT):
                    out.append(f)
            return out
        zips = find_zip("0")
    if not zips:
        return False
    f = zips[0]
    data = download_to_tmp(pwd_id, stoken, f)
    zpath = os.path.join(Q.DATA, "_tmp_" + f["file_name"])
    with open(zpath, "wb") as fh:
        fh.write(data)
    print(f"  下载 zip {f['file_name']} {len(data)//1024//1024}MB，解压中...", flush=True)
    exdir = zpath + ".d"
    os.makedirs(exdir, exist_ok=True)
    n = 0
    try:
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                nm = os.path.basename(info.filename)
                if not nm.lower().endswith(Q.AUDIO_EXT):
                    continue
                adata = z.read(info)
                if len(adata) < 30 * 1024:
                    continue
                stem = re.sub(r"^\s*\d{1,2}[\s\.\-_、]+", "", os.path.splitext(nm)[0])
                stem = re.sub(r"^\s*周杰伦\s*[-–—]\s*", "", stem)
                ext = os.path.splitext(nm)[1].lower()
                base = Q.safe_name(stem)
                dst = os.path.join(MUSIC_DIR, base + ext)
                tmp = dst + ".part"
                with open(tmp, "wb") as fh2:
                    fh2.write(adata)
                Q.tag(tmp, dst, {"title": stem, "artist": "周杰伦", "album": "周杰伦",
                                 "album_artist": "周杰伦"}, None)
                os.unlink(tmp)
                n += 1
    finally:
        try:
            os.unlink(zpath)
        except OSError:
            pass
        shutil.rmtree(exdir, ignore_errors=True)
    print(f"  解压入库 {n} 首", flush=True)
    return n > 0


def main() -> None:
    fails, by_core = load_fails()
    print(f"失败 {len(fails)} 首，开始抢救\n", flush=True)

    # 先处理 zip 专辑（6 个）
    zip_cores = ["11月的萧邦", "12新作", "依然范特西", "周杰伦的床边故事", "哎呦，不错哦", "我很忙"]
    for core in zip_cores:
        it = by_core.get(core)
        if not it:
            continue
        try:
            if handle_zip(it, core):
                pass
            else:
                print(f"ZIP 未找到: {core}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"ZIP FAIL {core}: {str(exc)[:100]}", flush=True)
        time.sleep(1.5)

    # 再重试 .wma 和 404
    for core, r in fails.items():
        if core in zip_cores:
            continue
        why = r["why"]
        if "pan.baidu" in why or "直链为空" in why:
            continue  # 百度云 / 失效跳过
        it = by_core.get(core)
        if not it:
            continue
        try:
            if handle_wma_404(it, core, r):
                pass
            else:
                print(f"RETRY 无结果: {core}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"RETRY FAIL {core}: {str(exc)[:90]}", flush=True)
        time.sleep(1.0)

    print("\n抢救完成", flush=True)


if __name__ == "__main__":
    main()
