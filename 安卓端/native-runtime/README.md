# ARM64 原生运行库构建

在 Linux x86_64 主机（可使用 Ubuntu 24.04 WSL 2）上使用 Android NDK r28c（`28.2.13676358`），目标为 Android API 29。解包前核对 Linux NDK ZIP 的 SHA-1 为 `a7b54a5de87fecd125a17d54f73c446199e72a64`。[Google 下载](https://dl.google.com/android/repository/android-ndk-r28c-linux.zip) · [SDK 元数据](https://dl.google.com/android/repository/repository2-3.xml)

Ubuntu 构建工具可用 `sudo apt install build-essential cmake ninja-build pkg-config perl python3 python3-setuptools unzip xz-utils autoconf automake libtool patch` 安装。WSL 下把 NDK 和中间产物放在 Linux 文件系统。

从发行配套的对应源码包提取 `sources/` 目录，为 `SOURCE_CACHE` 提供 [sources.sha256](sources.sha256) 中所列文件，也可由 [上游来源](SOURCES.md) 取得。使用原版 `youtubedl-android 0.18.1` 的两个 AAR 作为 Java 封装输入，脚本校验 AAR 并保留 `classes.jar` 与其他非原生条目。[library AAR](https://repo.maven.apache.org/maven2/io/github/junkfood02/youtubedl-android/library/0.18.1/library-0.18.1.aar) · [ffmpeg AAR](https://repo.maven.apache.org/maven2/io/github/junkfood02/youtubedl-android/ffmpeg/0.18.1/ffmpeg-0.18.1.aar)

从安卓项目根目录调用以下命令。路径需按本机实际位置设置，中间输出目录和 `.build/native-runtime` 须尚未存在。

```bash
ndk=/path/to/android-ndk-r28c
sources=/path/to/sources
upstream=/path/to/original-aars
work=$(mktemp -d)
bash native-runtime/build-ffmpeg.sh "$ndk" "$sources" "$work/ffmpeg"
bash native-runtime/build-quickjs.sh "$ndk" "$sources" "$work/quickjs"
bash native-runtime/build-python.sh "$ndk" "$sources" "$work/python"
mkdir -p .build
python3 native-runtime/stage-native-aars.py \
  --library-aar "$upstream/library-0.18.1.aar" \
  --ffmpeg-aar "$upstream/ffmpeg-0.18.1.aar" \
  --ffmpeg-dir "$work/ffmpeg" --quickjs "$work/quickjs/libqjs.so" \
  --python-dir "$work/python" --out-dir .build/native-runtime
```

脚本检查 Android PIE 和 16 KiB ELF 对齐。打包时保留旧 Java 加载器使用的 ZIP 路径，剔除 Python 内置的 pip 安装工具，记录两个 AAR 的 SHA-256。Gradle 在打包前按清单复核。正式构建和签名方式见 [安卓 README](../README.md#构建与签名正式包)。
