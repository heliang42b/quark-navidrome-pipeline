# -*- coding: utf-8 -*-
"""夸克合集包：递归列目录 → 逐个文件「转存→下载→删除」，尽量少占网盘空间。

用法：
    python quark_collection.py --list  "https://pan.quark.cn/s/xxxx"        # 只列目录
    python quark_collection.py --run   "https://pan.quark.cn/s/xxxx" 专辑名  # 真正下载
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quark_dl as Q

MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.join(os.path.expanduser("~"), "Music", "jay"))
AUDIO_EXT = (".flac", ".mp3", ".wav", ".ape", ".m4a", ".aac")


def list_dir(pwd_id: str, stoken: str, pdir: str = "0") -> list[dict]:
    det = Q.api("share/sharepage/detail", method="GET", params={
        "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": pdir, "force": "0",
        "_page": "1", "_size": "200", "_fetch_banner": "0",
        "_fetch_share": "1", "_fetch_total": "1"})
    return ((det.get("data") or {}).get("list")) or []


def walk(pwd_id: str, stoken: str, pdir: str = "0", depth: int = 0) -> list[dict]:
    out = []
    for f in list_dir(pwd_id, stoken, pdir):
        name = f.get("file_name") or ""
        if f.get("dir") or f.get("file_type") == 0:
            if depth < 3:
                out.extend(walk(pwd_id, stoken, f["fid"], depth + 1))
            continue
        if name.lower().endswith(AUDIO_EXT):
            out.append({"name": name, "fid": f["fid"], "size": f.get("size") or 0,
                        "token": f.get("share_fid_token")})
    return out


def clean_title(name: str) -> str:
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"^\s*\d{1,2}[\s\.\-_、]+", "", stem)
    stem = re.sub(r"^\s*周杰伦\s*[-–—]\s*", "", stem)
    return stem.strip() or name


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    mode, url = sys.argv[1], sys.argv[2]
    album = sys.argv[3] if len(sys.argv) > 3 else "周杰伦"
    pwd_id, passcode = Q.parse_share(url)
    stoken, _ = Q.share_files(pwd_id, passcode)

    files = walk(pwd_id, stoken)
    total = sum(f["size"] for f in files)
    print(f"共 {len(files)} 个音频文件，合计 {total/1024/1024:.1f} MB", flush=True)
    for f in files[:8]:
        print("   ", f["name"], f"{f['size']/1024/1024:.1f}MB")

    if mode == "--list":
        return

    os.makedirs(MUSIC_DIR, exist_ok=True)
    manifest = os.path.join(Q.DATA, "collection_manifest.jsonl")
    done = set()
    if os.path.exists(manifest):
        for line in open(manifest, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("ok"):
                    done.add(r["fid"])
            except Exception:  # noqa: BLE001
                pass

    ok = skip = fail = 0
    for i, f in enumerate(files, 1):
        title = clean_title(f["name"])
        ext = os.path.splitext(f["name"])[1].lower()
        dst = os.path.join(MUSIC_DIR, Q.safe_name(title) + ext)
        if f["fid"] in done or os.path.exists(dst):
            skip += 1
            continue
        try:
            before = Q.root_fids()
            saved = Q.save_and_wait(pwd_id, stoken, [f])
            if not saved:
                raise RuntimeError("转存失败")
            urls = Q.download_urls(saved)
            if not urls:
                raise RuntimeError("无直链")
            data = Q.fetch(list(urls.values())[0])
            if len(data) < 50 * 1024:
                raise RuntimeError("内容过小")
            tmp = dst + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            Q.tag(tmp, dst, {"title": title, "artist": "周杰伦", "album": album,
                             "album_artist": "周杰伦"}, None)
            os.unlink(tmp)
            ok += 1
            rec = {"ok": True, "fid": f["fid"], "title": title, "bytes": len(data)}
            print(f"[{i}/{len(files)}] OK {title}  {len(data)//1024}KB", flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            rec = {"ok": False, "fid": f["fid"], "title": title, "why": str(exc)[:150]}
            print(f"[{i}/{len(files)}] FAIL {title}  {str(exc)[:90]}", flush=True)
            if "空间" in str(exc) or "capacity" in str(exc):
                print("  网盘空间不足，先停", flush=True)
                break
        finally:
            try:
                after = Q.root_fids()
                left = sorted(after - before)
                if left:
                    Q.delete_files(left)
            except Exception:  # noqa: BLE001
                pass
        with open(manifest, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        time.sleep(1.0)
    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}", flush=True)


if __name__ == "__main__":
    main()
