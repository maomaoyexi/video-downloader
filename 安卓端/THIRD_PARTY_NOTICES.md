# 安卓第三方组件与对应源码

本清单适用于使用重建运行库的 `arm64-v8a` 正式包。安卓应用代码的许可和署名见 [LICENSE](LICENSE)。APK 内的第三方许可、版权和专利声明原文位于 `assets/third-party-licenses/`。

## 下载引擎与 Android 接口

| 组件 | APK 中的内容 | 许可与对应源码 |
| --- | --- | --- |
| yt-dlp | `2026.11.23`。官方 Unix zipapp 位于 `res/raw/ytdlp`，SHA-256 为 `e8665ed64d6b9172773e812f891fb707a0cb1ee8d9ef4fc1acb00cabee4c5256`。 | Unlicense。[同版源码](https://github.com/yt-dlp/yt-dlp/tree/2026.11.23) · [许可原文](https://github.com/yt-dlp/yt-dlp/blob/2026.11.23/LICENSE) · [官方发行文件](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23) |
| yt-dlp-ejs | `0.8.0`。随 yt-dlp zipapp 分发，内含 meriyah `6.1.4` 和 astring `1.9.0`。合并后的 `lib.min.js` 保留依赖许可。 | EJS 为 Unlicense，meriyah 为 ISC，astring 为 MIT。[EJS 同版源码](https://github.com/yt-dlp/ejs/tree/0.8.0) · [EJS 同版 PyPI 包](https://pypi.org/project/yt-dlp-ejs/0.8.0/) · [meriyah 同版 npm 包](https://registry.npmjs.org/meriyah/-/meriyah-6.1.4.tgz) · [astring 同版 npm 包](https://registry.npmjs.org/astring/-/astring-1.9.0.tgz) |
| youtubedl-android | `0.18.1`。保留上游 `library`、`ffmpeg` 的 JVM 代码和 `common` 模块。两个重建 AAR 使用本清单中的 ARM64 原生运行库。 | GPLv3。[固定上游源码与许可](https://github.com/yausername/youtubedl-android/tree/d725d5c9a18c3a99a13ee0308bf78275dc310760) · [同版 Maven 组件和源码包](https://repo.maven.apache.org/maven2/io/github/junkfood02/youtubedl-android/) |

## ARM64 原生运行库

| 组件 | APK 中的内容 | 许可与对应源码 |
| --- | --- | --- |
| FFmpeg 与 ffprobe | `7.1.1`。`libffmpeg.so` 和 `libffprobe.so` 为 Android 可执行文件，使用 `--enable-gpl --enable-version3` 并静态链接 WebP 和 OpenSSL。`libffmpeg.zip.so` 保留解包所需目录。 | GPL-3.0-or-later。[同版源码包](https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz) · [GPLv3 原文](https://github.com/FFmpeg/FFmpeg/blob/n7.1.1/COPYING.GPLv3) · [FFmpeg 许可说明](https://github.com/FFmpeg/FFmpeg/blob/n7.1.1/LICENSE.md) |
| WebP 与 SharpYUV | `1.6.0`。静态链接到 FFmpeg 和 ffprobe。 | BSD-3-Clause，含 WebM 项目专利声明。[固定源码提交](https://github.com/webmproject/libwebp/tree/4fa21912338357f89e4fd51cf2368325b59e9bd9) · [许可原文](https://github.com/webmproject/libwebp/blob/v1.6.0/COPYING) · [专利声明](https://github.com/webmproject/libwebp/blob/v1.6.0/PATENTS) |
| CPython | `3.12.11`。`libpython.so` 为启动程序。`libpython.zip.so` 含 `libpython3.12.so.1.0`、标准库、扩展和完整的 CPython 许可。 | PSF 及上游完整 `LICENSE` 中列明的许可。[同版源码](https://www.python.org/downloads/release/python-31211/) · [许可原文](https://github.com/python/cpython/blob/v3.12.11/LICENSE) |
| QuickJS | `2025-04-26`。`libqjs.so` 为交叉编译的解释器，运行 yt-dlp 的 EJS。 | MIT。[同版源码包与其中的 LICENSE](https://bellard.org/quickjs/quickjs-2025-04-26.tar.xz) |
| OpenSSL | `3.5.2`。静态链接到 FFmpeg、ffprobe 及 CPython 的 `_ssl`、`_hashlib`。 | Apache-2.0。[官方同版源码包](https://github.com/openssl/openssl/releases/tag/openssl-3.5.2) · [许可原文](https://github.com/openssl/openssl/blob/openssl-3.5.2/LICENSE.txt) |
| libffi | `3.4.6`。静态链接到 CPython 的 `_ctypes`。 | MIT。[同版源码](https://github.com/libffi/libffi/releases/tag/v3.4.6) · [许可原文](https://github.com/libffi/libffi/blob/v3.4.6/LICENSE) |
| bzip2 | `1.0.8`。静态链接到 CPython 的 `_bz2`。 | bzip2 上游许可。[同版源码包与其中的 LICENSE](https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz) |
| liblzma | XZ Utils `5.8.1` 的库，静态链接到 CPython 的 `_lzma`。 | 0BSD。[同版源码](https://github.com/tukaani-project/xz/tree/v5.8.1) · [许可范围](https://github.com/tukaani-project/xz/blob/v5.8.1/COPYING) · [0BSD 原文](https://github.com/tukaani-project/xz/blob/v5.8.1/COPYING.0BSD) |
| zlib | `1.3.1`。静态链接到 CPython 的 `zlib` 扩展。FFmpeg 和 ffprobe 调用 Android 系统的 `libz.so`。 | zlib License。[同版源码包](https://zlib.net/fossils/zlib-1.3.1.tar.gz) · [许可原文](https://github.com/madler/zlib/blob/v1.3.1/LICENSE) |
| SQLite | `3.50.4`。使用 SQLite amalgamation 构建并静态链接到 CPython 的 `_sqlite3`。 | SQLite 核心为公有领域。[对应源码包](https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz) · [版权说明](https://www.sqlite.org/copyright.html) |
| Expat | `2.7.1`。采用 CPython 源码附带的实现，静态链接到 `pyexpat`。 | MIT。[对应源码和许可](https://github.com/python/cpython/tree/v3.12.11/Modules/expat) |
| libmpdec | `2.5.1`。采用 CPython 源码附带的实现，静态链接到 `_decimal`。 | BSD-2-Clause。[对应源码及文件许可头](https://github.com/python/cpython/blob/v3.12.11/Modules/_decimal/libmpdec/mpdecimal.c) |
| certifi | `2025.11.12`。使用该版源码包中 Mozilla CA 证书数据，原样保存为 Python 归档的 `usr/etc/tls/cert.pem`。 | MPL-2.0。certifi 源码包内有证书源数据与来源说明。[对应源码包](https://pypi.org/project/certifi/2025.11.12/#files) · [MPL-2.0 原文](https://www.mozilla.org/MPL/2.0/) |
| PyCryptodomeX | `3.23.0`。Python 归档内的 `Cryptodome`，原生扩展从同版源码交叉编译。 | 公有领域及 BSD-2-Clause。[对应 PyPI 源码包](https://pypi.org/project/pycryptodomex/3.23.0/#files) · [许可原文](https://github.com/Legrandin/pycryptodome/blob/v3.23.0/LICENSE.rst) |
| Mutagen | `1.47.0`。Python 归档内的 `mutagen` 来自同版源码。 | GPL-2.0-or-later。[对应 PyPI 源码包](https://pypi.org/project/mutagen/1.47.0/#files) · [许可原文](https://github.com/quodlibet/mutagen/blob/release-1.47.0/COPYING) |

## Android 与 JVM 传递依赖

| 组件 | 许可与对应源码 |
| --- | --- |
| AndroidX | Apache-2.0。运行时包含 AppCompat `1.4.2`、Core 与 Core KTX `1.8.0` 及其传递组件。各组件的版本可从 Gradle 运行时依赖清单核对。[AndroidX 源码与许可](https://github.com/androidx/androidx) · [Google Maven 组件与同版源码包](https://maven.google.com/web/index.html) |
| Kotlin 标准库及 JetBrains Annotations | Apache-2.0。正式构建解析到 Kotlin 标准库 `2.2.10`、jdk7/jdk8 `1.8.0` 和 Annotations `13.0`。[同版 Maven 组件源码与校验值](native-runtime/jvm-sources.tsv) |
| Jackson Core、Databind、Annotations | `2.11.1`，Apache-2.0。归档中的 LICENSE 及 NOTICE 随许可资料提供。[Core](https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-core/2.11.1/) · [Databind](https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.11.1/) · [Annotations](https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-annotations/2.11.1/) |
| Apache Commons IO 和 Apache Commons Compress | 分别为 `2.5` 和 `1.12`，Apache-2.0。保留两者的 LICENSE 和 NOTICE。[Commons IO 对应源码包](https://repo.maven.apache.org/maven2/commons-io/commons-io/2.5/) · [Commons Compress 对应源码包](https://repo.maven.apache.org/maven2/org/apache/commons/commons-compress/1.12/) |
| Guava ListenableFuture | `1.0`，Apache-2.0。[同版组件与源码包](https://repo.maven.apache.org/maven2/com/google/guava/listenablefuture/1.0/) |

## 重建与对应源码

原生运行库使用 Android NDK r28c（`28.2.13676358`）交叉编译，目标为 Android API 29，ELF 加载段按 16 KiB 对齐。FFmpeg 的补丁在启用 TLS 验证时加载应用提供的 CA 信任路径，校验证书中的域名或 IP，并将相关设置传给 HLS 分片。CPython 的模块链接补丁使扩展显式链接 `libpython3.12.so.1.0`，以适配 Android 动态加载。重建脚本包含 libffi 的 Android 构建调整。[编译和 AAR 归档脚本](native-runtime/) · [源码输入与 SHA-256](native-runtime/sources.sha256) · [FFmpeg TLS 补丁](native-runtime/ffmpeg-openssl-peer-verification.patch) · [CPython 模块链接补丁](native-runtime/0010-link-modules-against-libpython.patch) · [CPython 补丁来源](https://github.com/termux/termux-packages/blob/4661b33dee05d9abb63b659656cce831eceb4557/packages/python/0010-link-modules-against-libpython.patch)

发行资料提供与签名 APK 对应的应用源码、分发的第三方组件源码、所用补丁和构建安装说明，以及 APK 的 SHA-256、依赖版本和许可原文。原生组件按输入锁中的文件和 SHA-256 重建。yt-dlp 按版本锁获取同版 zipapp。请沿用上游的版权、许可和专利声明。[安卓构建与安装说明](README.md#构建) · [yt-dlp 版本锁](core-lock.json) · [GPLv3 对应源码条款](https://www.gnu.org/licenses/gpl-3.0.html#section6)
