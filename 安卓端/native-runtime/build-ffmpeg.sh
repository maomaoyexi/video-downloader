#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

if [[ $# != 3 ]]; then
    printf 'Usage: bash %s NDK_DIR SOURCE_CACHE NEW_OUTPUT_DIR\n' "$0" >&2
    exit 2
fi

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    printf 'The pinned NDK toolchain requires a Linux x86_64 host.\n' >&2
    exit 2
fi

for command in make cmake ninja pkg-config perl python3 patch tar unzip sha256sum realpath; do
    command -v "$command" >/dev/null || { printf 'Missing host tool: %s\n' "$command" >&2; exit 2; }
done
ndk=$(realpath -- "$1")
sources=$(realpath -- "$2")
if ! grep -Eq '^Pkg.Revision[[:space:]]*=[[:space:]]*28\.2\.13676358[[:space:]]*$' "$ndk/source.properties"; then
    printf 'Expected Android NDK r28c (28.2.13676358) at %s\n' "$ndk" >&2
    exit 2
fi

toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
api=29
compiler="$toolchain/aarch64-linux-android${api}-clang"
compiler_cxx="$toolchain/aarch64-linux-android${api}-clang++"
"$compiler" --version
(cd -- "$sources" && sha256sum --check "$script_dir/sources.sha256")
(cd -- "$script_dir" && printf '%s  %s\n' \
    5d0d8fe2b815513dc99eb322939fefce5aa207ffabbcef4b653893a79b993e03 \
    ffmpeg-openssl-peer-verification.patch | sha256sum --check -)

mkdir -- "$3"
output=$(realpath -- "$3")
work=$(mktemp -d "${TMPDIR:-/tmp}/android-ffmpeg-arm64.XXXXXXXX")
trap 'printf "Build files: %s\n" "$work"' EXIT
prefix="$work/prefix"
jobs=${BUILD_JOBS:-$(nproc)}

tar -xf "$sources/ffmpeg-7.1.1.tar.xz" -C "$work"
patch --batch --forward --fuzz=0 -p1 -d "$work/ffmpeg-7.1.1" < "$script_dir/ffmpeg-openssl-peer-verification.patch"
unzip -q "$sources/libwebp-v1.6.0-git-source.zip" -d "$work"
tar -xf "$sources/openssl-3.5.2.tar.gz" -C "$work"

cmake -S "$work/libwebp-v1.6.0" -B "$work/webp-build" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM="android-$api" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF \
    -DWEBP_BUILD_CWEBP=OFF -DWEBP_BUILD_DWEBP=OFF -DWEBP_BUILD_GIF2WEBP=OFF \
    -DWEBP_BUILD_IMG2WEBP=OFF -DWEBP_BUILD_VWEBP=OFF -DWEBP_BUILD_WEBPINFO=OFF \
    -DWEBP_BUILD_LIBWEBPMUX=ON -DWEBP_BUILD_WEBPMUX=OFF \
    -DWEBP_BUILD_ANIM_UTILS=OFF -DWEBP_BUILD_EXTRAS=OFF
cmake --build "$work/webp-build" --parallel "$jobs"
cmake --install "$work/webp-build"

(
    cd -- "$work/openssl-3.5.2"
    export ANDROID_NDK_ROOT="$ndk" PATH="$toolchain:$PATH"
    perl ./Configure android-arm64 "-D__ANDROID_API__=$api" \
        --prefix="$prefix" --openssldir=/etc/ssl --libdir=lib \
        -fPIC no-shared no-tests no-apps no-module
    make -j "$jobs" build_libs
    make install_dev
    perl configdata.pm --dump > "$output/openssl-config.txt"
)

(
    cd -- "$work/ffmpeg-7.1.1"
    unset PKG_CONFIG_SYSROOT_DIR
    export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
    pkg-config --static --cflags --libs libwebp libwebpmux openssl > "$output/pkg-config.txt"
    ./configure \
        --target-os=android --arch=aarch64 --enable-cross-compile \
        --cc="$compiler" --cxx="$compiler_cxx" \
        --ar="$toolchain/llvm-ar" --nm="$toolchain/llvm-nm" \
        --ranlib="$toolchain/llvm-ranlib" --strip="$toolchain/llvm-strip" \
        --enable-static --disable-shared --enable-pic \
        --extra-ldflags=-Wl,-z,max-page-size=16384 --extra-ldexeflags=-pie \
        --extra-libs=-lm \
        --disable-autodetect --enable-gpl --enable-version3 --enable-zlib \
        --enable-openssl --enable-libwebp --pkg-config-flags=--static \
        --disable-ffplay --disable-doc --disable-debug || {
            cp ffbuild/config.log "$output/"
            tail -n 65 ffbuild/config.log >&2
            exit 1
        }
    make -j "$jobs" ffmpeg ffprobe
    install -m 755 ffmpeg "$output/libffmpeg.so"
    install -m 755 ffprobe "$output/libffprobe.so"
    cp ffbuild/config.mak ffbuild/config.log "$output/"
)

project=$(cd -- "$script_dir/.." && pwd -P)
python3 - "$project" "$output" <<'PY'
from pathlib import Path
from runpy import run_path
import sys

project, output = sys.argv[1:]
check_elf = run_path(Path(project) / 'prepare-ffmpeg.py')['check_elf']
for binary in ('libffmpeg.so', 'libffprobe.so'):
    path = Path(output) / binary
    check_elf(path.read_bytes(), 183, path.name)
PY

for binary in libffmpeg.so libffprobe.so; do
    "$toolchain/llvm-readelf" --wide --file-header --program-headers --dynamic \
        "$output/$binary" > "$output/$binary.elf.txt"
    if ! grep -Eq 'Type:[[:space:]]+DYN' "$output/$binary.elf.txt" ||
        ! grep -Fq '/system/bin/linker64' "$output/$binary.elf.txt"; then
        printf 'Expected the Android executable interpreter: %s\n' "$binary" >&2
        exit 1
    fi
done
cp "$work/webp-build/CMakeCache.txt" "$output/webp-config.txt"
(cd -- "$output" && sha256sum libffmpeg.so libffprobe.so > SHA256SUMS.txt)
printf 'Verified arm64-v8a ELF ABI and 16 KiB alignment: %s\n' "$output"
