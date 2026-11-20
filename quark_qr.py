# -*- coding: utf-8 -*-
"""夸克扫码登录：取二维码 token → 存 PNG → 轮询拿 ticket → 换 cookie。"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
OUT = os.path.dirname(os.path.abspath(__file__))


def get(url, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except Exception as exc:  # noqa: BLE001
        body = exc.read() if hasattr(exc, "read") else b""
        return getattr(exc, "code", 0), body, {}


st, body, _ = get("https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin",
                  {"Referer": "https://pan.quark.cn/"})
print("token status", st)
print(body[:400])
try:
    tok = json.loads(body.decode("utf-8"))["data"]["members"]["token"]
except Exception as exc:  # noqa: BLE001
    print("parse fail", exc)
    sys.exit(1)
print("TOKEN:", tok)

st2, img, hdr = get("https://uop.quark.cn/cas/qrlogin/qrcode?token=" + urllib.parse.quote(tok),
                    {"Referer": "https://pan.quark.cn/", "Accept": "image/avif,image/webp,*/*"})
print("qr status", st2, "type", hdr.get("Content-Type"), "len", len(img))
with open(os.path.join(OUT, "quark_qr.png"), "wb") as fh:
    fh.write(img)
print("saved:", os.path.join(OUT, "quark_qr.png"))
with open(os.path.join(OUT, "quark_token.txt"), "w", encoding="utf-8") as fh:
    fh.write(tok)
