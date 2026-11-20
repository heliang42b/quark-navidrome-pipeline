# -*- coding: utf-8 -*-
"""从站点的「网盘资源」搜索里找周杰伦的整张专辑（FLAC 优先），拿分享地址 + 曲目表。"""
import gzip
import json
import os
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ALBUM_HINTS = ("专辑", "album", "ALBUM", "FLAC", "flac", "无损", "全集", "合集", "收录")
BAD_ALBUM = ("演唱会", "MV", "伴奏", "翻唱", "铃声", "DJ", "混音", "抖音", "KTV")


def req(url, payload=None, timeout=30):
    h = {"User-Agent": UA, "Referer": "https://so.liumingye.cn/"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8", "replace"))


items = []
for kw in ("周杰伦 专辑", "周杰伦 FLAC", "周杰伦 无损", "周杰伦 无损专辑"):
    for page in (1, 2):
        try:
            d = req("https://so.liumingye.cn/api/source/search?" + urllib.parse.urlencode(
                {"q": kw, "page": str(page), "pageSize": "20"}))
            got = d.get("data") or []
            items.extend(got)
            print(f"{kw} p{page}: {len(got)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{kw} p{page} FAIL {str(exc)[:60]}")
        time.sleep(2.6)

seen, cand = set(), []
for it in items:
    title = it.get("title") or ""
    iid = it.get("id")
    if not iid or iid in seen:
        continue
    seen.add(iid)
    if "周杰伦" not in title and "Jay" not in title:
        continue
    if any(b in title for b in BAD_ALBUM):
        continue
    menu = it.get("menu") or ""
    n_audio = sum(1 for ln in menu.splitlines() if ln.strip().lower().endswith((".flac", ".mp3", ".wav", ".ape")))
    cand.append({"id": iid, "title": title, "type": it.get("type"), "n_audio": n_audio,
                 "menu": menu})

cand.sort(key=lambda x: -x["n_audio"])
print(f"候选专辑包：{len(cand)}")
for c in cand[:20]:
    print(f"  [{c['type']}] {c['n_audio']:3d} 首  {c['title'][:60]}")

out = []
for c in cand:
    if c["n_audio"] < 3:
        continue
    try:
        g = req("https://so.liumingye.cn/api/source/geturl", {"id": c["id"]})
        c["url"] = g.get("url")
    except Exception as exc:  # noqa: BLE001
        c["url"] = None
        print("geturl fail", c["title"][:30], str(exc)[:50])
    out.append(c)
    time.sleep(2.6)

json.dump(out, open(os.path.join(DATA, "albums.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
quark = [c for c in out if (c.get("url") or "").find("pan.quark.cn") >= 0]
print(f"\n可用专辑包 {len(out)} 个，其中夸克 {len(quark)} 个，合计约 {sum(c['n_audio'] for c in quark)} 首")
for c in quark[:15]:
    print(f"  {c['n_audio']:3d} 首  {c['title'][:56]}  {c['url']}")
