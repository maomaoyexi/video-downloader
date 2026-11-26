#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
version=2025-04-26
if [[ $# != 3 ]]; then
    printf 'Usage: bash %s NDK_DIR SOURCE_CACHE NEW_OUTPUT_DIR\n' "$0" >&2
    exit 2
fi

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    printf 'The pinned NDK toolchain requires a Linux x86_64 host.\n' >&2
    exit 2
fi

for command in cc make tar xz sha256sum python3 realpath; do
    command -v "$command" >/dev/null || { printf 'Missing host tool: %s\n' "$command" >&2; exit 2; }
done

ndk=$(realpath -- "$1")
sources=$(realpath -- "$2")
source_archive="$sources/quickjs-$version.tar.xz"
if ! grep -Eq '^Pkg\.Revision[[:space:]]*=[[:space:]]*28\.2\.13676358[[:space:]]*$' "$ndk/source.properties"; then
    printf 'Expected Android NDK r28c (28.2.13676358) at %s\n' "$ndk" >&2
    exit 2
fi

toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
compiler=aarch64-linux-android29-clang
"$toolchain/$compiler" --version
(cd -- "$sources" && sha256sum --check "$script_dir/sources.sha256")

mkdir -- "$3"
output=$(realpath -- "$3")
work=$(mktemp -d "${TMPDIR:-/tmp}/android-quickjs-arm64.XXXXXXXX")
trap 'printf "Build files: %s\n" "$work"' EXIT
jobs=${BUILD_JOBS:-$(nproc)}

mkdir -- "$work/host" "$work/target"
tar -xf "$source_archive" -C "$work/host" --strip-components=1
tar -xf "$source_archive" -C "$work/target" --strip-components=1

# Like Termux's Makefile.patch at e8a4d299, keep the native qjsc compiler
# free of Android flags. Separate source trees also isolate the object files.
make -C "$work/host" -j "$jobs" CC=cc CONFIG_LTO= qjsc
(
    cd -- "$work/target"
    export PATH="$toolchain:$PATH"
    CFLAGS='-fPIE -D__BIONIC_NO_PAGE_SIZE_MACRO' make -j "$jobs" \
        CONFIG_CLANG=y CONFIG_DEFAULT_AR=y CONFIG_LTO= CROSS_PREFIX= \
        CC="$compiler" AR=llvm-ar QJSC=../host/qjsc \
        LDFLAGS='-pie -Wl,-z,max-page-size=16384' LIBS='-lm -ldl' qjs
    "$toolchain/llvm-strip" --strip-unneeded qjs
    install -m 755 qjs "$output/libqjs.so"
)

project=$(cd -- "$script_dir/.." && pwd -P)
python3 - "$project" "$output/libqjs.so" <<'PY'
from pathlib import Path
from runpy import run_path
import sys

project, binary = map(Path, sys.argv[1:])
check_elf = run_path(project / 'prepare-ffmpeg.py')['check_elf']
check_elf(binary.read_bytes(), 183, binary.name)
PY

LC_ALL=C "$toolchain/llvm-readelf" --wide --file-header --program-headers --dynamic \
    "$output/libqjs.so" > "$output/libqjs.so.elf.txt"
if ! grep -Eq 'Type:[[:space:]]+DYN' "$output/libqjs.so.elf.txt" ||
    ! grep -Fq '/system/bin/linker64' "$output/libqjs.so.elf.txt"; then
    printf 'Expected an Android PIE executable: libqjs.so\n' >&2
    exit 1
fi

(cd -- "$output" && sha256sum libqjs.so > SHA256SUMS.txt)
printf 'Verified arm64-v8a ELF ABI and 16 KiB alignment: %s\n' "$output/libqjs.so"
