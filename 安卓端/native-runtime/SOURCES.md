# 固定源码来源

配套源码目录中各文件按 [SHA-256 清单](sources.sha256) 校验。补丁随构建脚本提供。

| 缓存文件 | 对应来源 |
| --- | --- |
| `ffmpeg-7.1.1.tar.xz` | [FFmpeg 源码包](https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz) |
| `libwebp-v1.6.0-git-source.zip` | [WebP 固定 Git 提交](https://github.com/webmproject/libwebp/tree/4fa21912338357f89e4fd51cf2368325b59e9bd9)。使用 `git archive --format=zip --prefix=libwebp-v1.6.0/ -6 4fa21912338357f89e4fd51cf2368325b59e9bd9 -o libwebp-v1.6.0-git-source.zip`。 |
| `openssl-3.5.2.tar.gz` | [OpenSSL 源码包](https://github.com/openssl/openssl/releases/tag/openssl-3.5.2) |
| `quickjs-2025-04-26.tar.xz` | [QuickJS 源码包](https://bellard.org/quickjs/quickjs-2025-04-26.tar.xz) |
| `Python-3.12.11.tar.xz` | [Python 源码包](https://www.python.org/downloads/release/python-31211/) |
| `libffi-3.4.6.tar.gz` | [Ubuntu 原始源码归档](https://archive.ubuntu.com/ubuntu/pool/main/libf/libffi/libffi_3.4.6.orig.tar.gz) |
| `bzip2-1.0.8.tar.gz` | [bzip2 源码包](https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz) |
| `xz-5.8.1.tar.xz` | [Debian Snapshot 原始源码归档](https://snapshot.debian.org/file/c29df8058b6279bfab2744f3e79b2940229207a3) |
| `zlib-1.3.1.tar.gz` | [zlib 源码包](https://zlib.net/fossils/zlib-1.3.1.tar.gz) |
| `sqlite-autoconf-3500400.tar.gz` | [SQLite 源码包](https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz) |
| `mutagen-1.47.0.tar.gz` | [Mutagen 源码包](https://pypi.org/project/mutagen/1.47.0/#files) |
| `pycryptodomex-3.23.0.tar.gz` | [PyCryptodomeX 源码包](https://pypi.org/project/pycryptodomex/3.23.0/#files) |
| `certifi-2025.11.12.tar.gz` | [certifi 与 Mozilla CA 数据](https://pypi.org/project/certifi/2025.11.12/#files) |
| `MPL-2.0.txt` | [Mozilla 许可原文](https://www.mozilla.org/media/MPL/2.0/index.815ca599c9df.txt)，与 Ubuntu 24.04 的 `/usr/share/common-licenses/MPL-2.0` 一致。 |

应用解析核心使用 yt-dlp 2026.11.23 的 Unix zipapp，对应 [core-lock.json](../core-lock.json) 和 [固定提交](https://github.com/yt-dlp/yt-dlp/tree/6f73a8d1664a58cdef8c25f01ffb5ab9cf730408)。原生封装的 Java 接口使用 [youtubedl-android 固定源码](https://github.com/yausername/youtubedl-android/tree/d725d5c9a18c3a99a13ee0308bf78275dc310760)。Maven 源码及校验值见 [JVM 源码清单](jvm-sources.tsv)，实际编入的组件许可见 [第三方许可清单](../THIRD_PARTY_NOTICES.md)。
