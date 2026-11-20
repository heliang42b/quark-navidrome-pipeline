# quark-navidrome-pipeline

把网盘里的音乐整理成一个干净、带标签、可直接被 [Navidrome](https://www.navidrome.org/) 索引的曲库。

这套脚本最初是为了把一个华语歌手的全部作品从「下歌吧（so.liumingye.cn）」上的网盘分享搬进自建 Navidrome 而写的，跑通后抽成通用流程。

## 流程

```
下歌吧搜索结果 ──harvest.py──▶ data/page_*.json
                                   │
                          analyze.py 归并去重
                                   │
                        siteshares.py 选最高音质 + 取夸克分享
                                   │
                            data/shares.json
                                   │
   quark_qr.py 扫码登录 ──▶ data/quark_cookie.txt
                                   │
        quark_dl.py 转存 ▶ 直链 ▶ 下载 ▶ 打标签 ▶ 入库
                                   │
                     rescue.py 抢救失败项 / 整张专辑 zip
                                   │
                     retag.py 补专辑名与音轨号（酷狗）
                                   │
                     cleanup.py 清掉翻唱、噪音、重名
                                   │
                     verify_db.py 核对 Navidrome 库里的数
```

另一条支线是酷我直链（`plan.py` → `download.py`），不依赖网盘，适合站点没有的资源；`artist_*.py` 则面向 FLAC 站点批量抓某个歌手的全部作品。

## 案例

[docs/CASE-STUDY.md](docs/CASE-STUDY.md) 记录了一次真实完整运行：319 个歌名里入库 259 首（5.22 GB），包括五类失败的成因、限速实测数据和五条结论。

## 环境

- Python 3.10+
- `ffmpeg` / `ffprobe` 在 PATH 里（打标签、加封面、转码要用）
- 只需要标准库，没有第三方依赖

## 环境变量

所有路径都不写死，靠环境变量覆盖：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `MUSIC_DIR` | `~/Music/jay` | 单歌手模式的入库目录 |
| `MUSIC_ROOT` | `~/Music` | 多歌手模式下的根目录，按 `<歌手>` 分子目录 |
| `FFMPEG` | `ffmpeg` | ffmpeg 可执行文件路径 |
| `FFPROBE` | `ffprobe` | ffprobe 可执行文件路径 |
| `NAVIDROME_DB` | `C:/ProgramData/Navidrome/navidrome.db` | Navidrome 的 SQLite 库（只读打开） |
| `ARTIST` | `周杰伦` | `verify_db.py` 统计时用的歌手名 |

## 使用

```bash
# 0. 准备
export MUSIC_DIR="/data/music/周杰伦"
mkdir -p data

# 1. 抓站点搜索结果（内置限速，约 2.7s/页，支持断点续抓）
python harvest.py

# 2. 归并成候选清单
python analyze.py

# 3. 挑最高音质、拿到夸克分享链接
python siteshares.py

# 4. 扫码登录夸克，把 cookie 落到 data/quark_cookie.txt
python quark_qr.py

# 5. 转存 → 直链 → 下载 → 打标签 → 入库
python quark_dl.py

# 6. 抢救失败项（限流、直链为空、整张专辑 zip）
python rescue.py

# 7. 补全专辑名和音轨号
python retag.py

# 8. 清理翻唱、伴奏、噪音、重名文件
python cleanup.py --dry   # 先看要删什么
python cleanup.py

# 9. 核对 Navidrome 库
python verify_db.py
```

清网盘残留：

```bash
python quark_dl.py --clean
```

## 几个踩过的坑

- **站点限速**：`/api/music/search` 60 秒内 30 次，超了封 180 秒。`harvest.py` 按每分钟 22 次跑，别调快。
- **夸克转存要等**：转存是异步任务，必须轮询 `task` 接口到 `status=2` 才拿得到直链，且刚转存完取直链可能 404，要退避重试。
- **大文件需要 SVIP**：超过夸克免费额度的整专辑压缩包会报 `download file size limit`，只能等次日额度或跳过。
- **同名不同版本**：先抓的 128k mp3 会和后来的 FLAC 撞名，`quark_dl.py` 入库时会顺手删掉旧的低码率文件。
- **标签优先级**：`artist` 写歌手名、`album_artist` 写同一个名字，Navidrome 才不会把合辑拆成一堆「未知艺术家」。

## 声明

仅供个人备份与管理自己有权使用的音乐资源。脚本本身不提供任何音频内容，所有内容来自第三方站点与网盘分享，请遵守当地法律与平台条款，不要用于传播侵权内容。

## License

MIT
