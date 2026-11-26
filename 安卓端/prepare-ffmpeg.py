"""Prepare the pinned youtubedl-android FFmpeg AAR with 16 KiB WebP libraries."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from struct import unpack_from
import tarfile
from tempfile import NamedTemporaryFile
from urllib.request import urlopen
from zipfile import ZipFile


VERSION = "0.18.1"
UPSTREAM_AAR = (
    f"https://repo.maven.apache.org/maven2/io/github/junkfood02/youtubedl-android/ffmpeg/{VERSION}/ffmpeg-{VERSION}.aar",
    "0a87ffa6cf912b0fe76c1a99b9107f543ee2f247935fae2c71f0822eb7bc5f49",
)
WEBP_VERSION = "1.6.0.0.0.1%2Breally1.6.0"
ABI = "arm64-v8a"
WEBP_SHA256 = "8ba7fcfadd1a9957a7632c6407d6ef3e41d34dbd96a41769b245592ed4559045"
WEBP_LIBRARIES = ("libsharpyuv.so", "libwebpdecoder.so", "libwebp.so", "libwebpdemux.so", "libwebpmux.so")
TERMUX_POOL = "https://packages.termux.dev/apt/termux-main/pool/main/libw/libwebp"
OUTPUT = Path(__file__).resolve().parent / ".build" / "runtime" / f"ffmpeg-{VERSION}-webp16k.aar"


def verified(data, expected, source):
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"SHA-256 校验失败：{source}")
    return data


def download(url, expected):
    with urlopen(url, timeout=60) as response:
        return verified(response.read(), expected, url)


def deb_payload(package):
    if not package.startswith(b"!<arch>\n"):
        raise ValueError("无效的 Debian 软件包")
    offset = 8
    while offset + 60 <= len(package):
        header = package[offset:offset + 60]
        name = header[:16].strip().rstrip(b"/")
        size = int(header[48:58])
        start = offset + 60
        if name == b"data.tar.xz":
            return package[start:start + size]
        offset = start + size + size % 2
    raise ValueError("WebP 软件包缺少 data.tar.xz")


def check_elf(data, machine, name):
    if data[:6] != b"\x7fELF\x02\x01" or unpack_from("<H", data, 18)[0] != machine:
        raise ValueError(f"ELF 架构不匹配：{name}")
    table = unpack_from("<Q", data, 32)[0]
    size, count = unpack_from("<HH", data, 54)
    loads = []
    for index in range(count):
        kind, _, offset, address, _, _, _, alignment = unpack_from("<IIQQQQQQ", data, table + size * index)
        if kind == 1:
            loads.append(alignment >= 16384 and (address - offset) % 16384 == 0)
    if not loads or not all(loads):
        raise ValueError(f"ELF 未按 16 KiB 对齐：{name}")


def webp_libraries():
    package = download(f"{TERMUX_POOL}/libwebp_{WEBP_VERSION}_aarch64.deb", WEBP_SHA256)
    with tarfile.open(fileobj=BytesIO(deb_payload(package)), mode="r:xz") as archive:
        result = {}
        for name in WEBP_LIBRARIES:
            member = archive.getmember(f"./data/data/com.termux/files/usr/lib/{name}")
            if not member.isfile():
                raise ValueError(f"WebP 库不是常规文件：{name}")
            with archive.extractfile(member) as stream:
                data = stream.read()
            check_elf(data, 183, name)
            result[f"usr/lib/{name}"] = data
        return result


def replace_zip_entries(source, destination, replacements, jni_abi=None):
    with ZipFile(BytesIO(source)) as original, ZipFile(destination, "w") as patched:
        missing = replacements.keys() - set(original.namelist())
        if missing:
            raise ValueError(f"压缩包中找不到替换条目：{', '.join(sorted(missing))}")
        for info in original.infolist():
            if jni_abi and info.filename.startswith("jni/") and info.filename != "jni/":
                if not info.filename.startswith(f"jni/{jni_abi}/"):
                    continue
            data = replacements[info.filename] if info.filename in replacements else original.read(info)
            patched.writestr(info, data)
        patched.comment = original.comment


def prepare(upstream_path):
    url, expected = UPSTREAM_AAR
    upstream = verified(upstream_path.read_bytes(), expected, upstream_path) if upstream_path else download(url, expected)
    name = f"jni/{ABI}/libffmpeg.zip.so"
    with ZipFile(BytesIO(upstream)) as original:
        bundle = original.read(name)
    patched = BytesIO()
    replace_zip_entries(bundle, patched, webp_libraries())
    if len(patched.getbuffer()) == len(bundle):
        raise ValueError(f"FFmpeg 归档长度未变化，覆盖安装后无法触发重新解包：{ABI}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=OUTPUT.parent, delete=False) as target:
        temporary = Path(target.name)
    try:
        replace_zip_entries(upstream, temporary, {name: patched.getvalue()}, jni_abi=ABI)
        temporary.replace(OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"已核验并生成 {OUTPUT.name}（{ABI}）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-aar", type=Path, help="使用本机缓存的上游 AAR，仍校验锁定的 SHA-256")
    prepare(parser.parse_args().upstream_aar)
