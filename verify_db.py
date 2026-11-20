# -*- coding: utf-8 -*-
"""Count the library through Navidrome's SQLite DB (read-only).

Set NAVIDROME_DB if your database lives elsewhere (default path below).
Set ARTIST to check a different artist (default: 周杰伦).
"""
import os
import sqlite3

DB = os.environ.get("NAVIDROME_DB", "C:/ProgramData/Navidrome/navidrome.db")
ARTIST = os.environ.get("ARTIST", "周杰伦")

c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
cur = c.cursor()
like = "%" + ARTIST + "%"

cur.execute("select count(*) from media_file where (artist like ? or album_artist like ?) and missing=0", (like, like))
print(f"{ARTIST} 有效歌曲数(非 missing):", cur.fetchone()[0])

cur.execute("select count(*) from media_file where (artist like ? or album_artist like ?) and missing=1", (like, like))
print(f"{ARTIST} missing 数:", cur.fetchone()[0])

cur.execute("""
select album, count(*) as n, suffix
from media_file
where artist like ? or album_artist like ?
group by album, suffix
order by n desc
limit 40
""", (like, like))
print("\n专辑分布:")
for album, n, suffix in cur.fetchall():
    print(f"  {(album or '')[:30]:32s} {n:3d}  {suffix}")

c.close()