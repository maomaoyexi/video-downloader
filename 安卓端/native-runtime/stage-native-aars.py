#!/usr/bin/env python3
"""Prepare ARM64 runtime AARs, preserving youtubedl-android 0.18.1 Java code."""

import argparse
from copy import copy
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from struct import unpack_from
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


ABI = "arm64-v8a"
JNI = f"jni/{ABI}/"
ARM64 = 183
PAGE_SIZE = 16384
VERSION = "0.18.1"
LIBRARY_SHA256 = "579b5fb480892b1abc2b218c2089699d52759cc8d7ba256bf876453f0365faef"
FFMPEG_SHA256 = "0a87ffa6cf912b0fe76c1a99b9107f543ee2f247935fae2c71f0822eb7bc5f49"
PYTHON_VERSION = "3.12"
SHARED_OBJECT = re.compile(r"\.so(?:\.[0-9]+)*$")


def describe(data):
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


def read_verified(path, expected_hash):
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"锁定的上游 AAR SHA-256 不匹配：{path}")
    return data


def check_elf(data, name, *, executable=False):
    if len(data) < 64 or not data.startswith(b"\x7fELF\x02\x01"):
        raise ValueError(f"需要 64 位小端 ELF：{name}")
    elf_type, machine = unpack_from("<HH", data, 16)
    entry, table = unpack_from("<QQ", data, 24)
    size, count = unpack_from("<HH", data, 54)
    if machine != ARM64 or elf_type != 3 or size < 56 or table + size * count > len(data):
        raise ValueError(f"ARM64 ELF 类型或程序头无效：{name}")
    loads = 0
    interpreters = []
    for i in range(count):
        kind, _, offset, va, _, file_size, _, align = unpack_from("<IIQQQQQQ", data, table + size * i)
        if kind not in (1, 3):
            continue
        if offset + file_size > len(data):
            raise ValueError(f"ELF 段超出文件：{name}")
        if kind == 1:
            loads += 1
            if align < PAGE_SIZE or (va - offset) % PAGE_SIZE:
                raise ValueError(f"ELF 加载段未按 16 KiB 对齐：{name}")
        else:
            interpreters.append(data[offset:offset + file_size])
    if not loads:
        raise ValueError(f"ELF 缺少加载段：{name}")
    if executable and (not entry or interpreters != [b"/system/bin/linker64\0"]):
        raise ValueError(f"需要可执行的 Android ARM64 PIE：{name}")


def zip_entry(name, mode, *, compressed=False):
    entry = ZipInfo(name)
    entry.create_system = 3  # Unix permissions and symlink type for ZipUtils.unzip.
    entry.external_attr = mode << 16
    if mode & stat.S_IFDIR:
        entry.external_attr |= 0x10
    entry.compress_type = ZIP_DEFLATED if compressed else ZIP_STORED
    return entry


def check_link(path, usr):
    target = os.readlink(path)
    if Path(target).is_absolute() or any(c in target for c in "\\:\r\n"):
        raise ValueError(f"只允许 Android 相对符号链接：{path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(usr) or not resolved.is_file():
        raise ValueError(f"符号链接必须指向 usr/ 内的文件：{path}")
    return target.encode("utf-8")


def read_python_tree(runtime, output):
    usr = runtime / "usr"
    standard_library = usr / "lib" / f"python{PYTHON_VERSION}"
    cert = usr / "etc" / "tls" / "cert.pem"
    if not usr.is_dir() or usr.is_symlink() or output.is_relative_to(usr):
        raise ValueError("Python 输入需要独立的 usr/ 目录")
    required = [standard_library / "encodings" / "__init__.py", cert]
    if not tuple((usr / "lib").glob(f"libpython{PYTHON_VERSION}.so*")) or not all(path.is_file() for path in required):
        raise ValueError(f"usr/ 中缺少 CPython {PYTHON_VERSION} 运行库、标准库或证书")
    if b"-----BEGIN CERTIFICATE-----" not in cert.read_bytes():
        raise ValueError("usr/etc/tls/cert.pem 缺少 PEM 证书")

    entries = {}
    elf_count = 0
    for directory, dirs, files in os.walk(usr, followlinks=False):
        current = Path(directory)
        if current == standard_library and "ensurepip" in dirs:
            dirs.remove("ensurepip")
        directories = [current, *(current / name for name in dirs if (current / name).is_symlink())]
        for path in (*directories, *(current / name for name in files)):
            name = path.relative_to(runtime).as_posix()
            if any(c in name for c in "\\:\r\n"):
                raise ValueError(f"usr/ 路径无法在 Android 上使用：{name}")
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries[name] = (stat.S_IFLNK | 0o777, check_link(path, usr))
            elif stat.S_ISDIR(mode):
                entries[f"{name}/"] = (stat.S_IFDIR | 0o755, b"")
            elif stat.S_ISREG(mode):
                data = path.read_bytes()
                if name.endswith(".zip.so"):
                    raise ValueError(f"usr/ 不应含有内嵌原生库归档：{name}")
                if data.startswith(b"\x7fELF") or SHARED_OBJECT.search(name):
                    check_elf(data, name)
                    elf_count += 1
                entries[name] = (stat.S_IFREG | (0o755 if mode & 0o111 else 0o644), data)
            else:
                raise ValueError(f"usr/ 不支持此文件类型：{name}")
    if not any(re.fullmatch(rf"usr/lib/libpython{re.escape(PYTHON_VERSION)}\.so(?:\.\d+)*", name)
               and stat.S_ISREG(mode) for name, (mode, _) in entries.items()):
        raise ValueError(f"usr/lib/ 缺少可装载的 CPython {PYTHON_VERSION} ELF")
    return entries, elf_count


def runtime_zip(entries, previous_length):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for name, (mode, contents) in sorted(entries.items()):
            archive.writestr(zip_entry(name, mode, compressed=stat.S_ISREG(mode)), contents)
    if len(data.getbuffer()) == previous_length:
        # The 0.18.1 extraction cache uses the archive length. Changing the
        # comment preserves the entries and forces extraction after upgrade.
        with ZipFile(data, "a") as archive:
            archive.comment = b"ARM64 native rebuild"
    rebuilt = data.getvalue()
    with ZipFile(BytesIO(rebuilt)) as archive:
        if len(rebuilt) == previous_length or archive.testzip() or set(archive.namelist()) != set(entries):
            raise ValueError("运行库 ZIP 校验失败")
    return rebuilt


def rebuilt_aar(source_data, replacements):
    data = BytesIO()
    with ZipFile(BytesIO(source_data)) as source, ZipFile(data, "w") as destination:
        expected = {JNI + name for name in replacements}
        sources = {name for name in source.namelist() if name.startswith(JNI) and not name.endswith("/")}
        if sources != expected:
            raise ValueError("AAR 的 ARM64 原生文件清单与锁定版本不符")
        expected_non_native = {}
        for entry in source.infolist():
            name = entry.filename
            if name.startswith("jni/") and name != "jni/" and not name.startswith(JNI):
                continue
            if name in expected:
                contents = replacements[name.removeprefix(JNI)]
            else:
                contents = source.read(entry)
                expected_non_native[name] = sha256(contents).hexdigest()
            destination.writestr(copy(entry), contents)
        destination.comment = source.comment
    result = data.getvalue()
    with ZipFile(BytesIO(result)) as candidate:
        if set(candidate.namelist()) != expected_non_native.keys() | expected:
            raise ValueError("候选 AAR 包含额外的归档成员")
        for name, expected_hash in expected_non_native.items():
            if sha256(candidate.read(name)).hexdigest() != expected_hash:
                raise ValueError(f"非替换成员的内容发生变化：{name}")
        for name, contents in replacements.items():
            if candidate.read(JNI + name) != contents:
                raise ValueError(f"替换成员校验失败：{name}")
    return result, expected_non_native["classes.jar"]


def stage(args):
    output = args.out_dir.resolve()
    if output.exists() or args.out_dir.is_symlink():
        raise ValueError(f"输出目录已存在，请指定新目录：{output}")
    library = read_verified(args.library_aar, LIBRARY_SHA256)
    ffmpeg = read_verified(args.ffmpeg_aar, FFMPEG_SHA256)
    runtime = args.python_dir.resolve(strict=True)
    bins = {
        "libpython.so": (runtime / "libpython.so").read_bytes(),
        "libqjs.so": args.quickjs.read_bytes(),
        "libffmpeg.so": (args.ffmpeg_dir / "libffmpeg.so").read_bytes(),
        "libffprobe.so": (args.ffmpeg_dir / "libffprobe.so").read_bytes(),
    }
    for name, contents in bins.items():
        check_elf(contents, name, executable=True)

    python_entries, elf_count = read_python_tree(runtime, output)
    ffmpeg_dirs = {f"{name}/": (stat.S_IFDIR | 0o755, b"") for name in ("usr", "usr/lib")}
    targets = {
        "library": (library, "libpython.zip.so", python_entries, ("libpython.so", "libqjs.so")),
        "ffmpeg": (ffmpeg, "libffmpeg.zip.so", ffmpeg_dirs, ("libffmpeg.so", "libffprobe.so")),
    }
    products = {}
    details = {}
    for name, (upstream, archive_name, entries, executable_names) in targets.items():
        with ZipFile(BytesIO(upstream)) as original:
            previous_length = original.getinfo(JNI + archive_name).file_size
        archive = runtime_zip(entries, previous_length)
        replacements = {file: bins[file] for file in executable_names}
        replacements[archive_name] = archive
        filename = f"{name}-{VERSION}-arm64-rebuilt.aar"
        result, classes_hash = rebuilt_aar(upstream, replacements)
        products[filename] = result
        details[filename] = {
            "upstream_aar": describe(upstream),
            "rebuilt_aar": describe(result),
            "classes_jar_sha256": classes_hash,
            "arm64_entries": {file: describe(contents) for file, contents in replacements.items()},
            "upstream_runtime_zip_bytes": previous_length,
            "rebuilt_runtime_zip_entries": len(entries),
        }

    output.mkdir()
    for filename, data in products.items():
        (output / filename).write_bytes(data)
    manifest = {"abi": ABI, "python_version": PYTHON_VERSION, "python_nested_elf_count": elf_count, "aars": details}
    (output / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{sha256(data).hexdigest()}  {name}\n" for name, data in products.items()
    ), encoding="utf-8")
    print(f"已校验四个 Android ARM64 PIE、Python 归档内 {elf_count} 个 ELF 及 16 KiB 对齐。")
    for filename in products:
        print(output / filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-aar", type=Path, required=True, help="原始 library-0.18.1.aar")
    parser.add_argument("--ffmpeg-aar", type=Path, required=True, help="原始 ffmpeg-0.18.1.aar")
    parser.add_argument("--ffmpeg-dir", type=Path, required=True, help="含 libffmpeg.so 和 libffprobe.so 的重建目录")
    parser.add_argument("--quickjs", type=Path, required=True, help="重建的 libqjs.so")
    parser.add_argument("--python-dir", type=Path, required=True, help="含重建 libpython.so 和 usr/ 的目录")
    parser.add_argument("--out-dir", type=Path, required=True, help="尚未存在的输出目录")
    stage(parser.parse_args())


if __name__ == "__main__":
    main()
