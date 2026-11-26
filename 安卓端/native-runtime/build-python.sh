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
for command in python3.12 make autoreconf automake libtoolize pkg-config perl patch tar sha256sum realpath; do
    command -v "$command" >/dev/null || { printf 'Missing host tool: %s\n' "$command" >&2; exit 2; }
done
host_python=$(command -v python3.12)
"$host_python" -c 'import setuptools; print("Build-time setuptools", setuptools.__version__)'

ndk=$(realpath -- "$1")
cache=$(realpath -- "$2")
if ! grep -Eq '^Pkg.Revision[[:space:]]*=[[:space:]]*28\.2\.13676358[[:space:]]*$' "$ndk/source.properties"; then
    printf 'Expected Android NDK r28c (28.2.13676358) at %s\n' "$ndk" >&2
    exit 2
fi

python_source="$cache/Python-3.12.11.tar.xz"
module_link_patch="$script_dir/0010-link-modules-against-libpython.patch"
openssl_source="$cache/openssl-3.5.2.tar.gz"
mutagen_source="$cache/mutagen-1.47.0.tar.gz"
crypto_source="$cache/pycryptodomex-3.23.0.tar.gz"
ffi_source="$cache/libffi-3.4.6.tar.gz"
bzip_source="$cache/bzip2-1.0.8.tar.gz"
xz_source="$cache/xz-5.8.1.tar.xz"
zlib_source="$cache/zlib-1.3.1.tar.gz"
sqlite_source="$cache/sqlite-autoconf-3500400.tar.gz"
ca_source="$cache/certifi-2025.11.12.tar.gz"
mpl_source="$cache/MPL-2.0.txt"

# Cache inputs retain their upstream bytes, including mirror filenames:
# libffi: https://mirrors.huaweicloud.com/ubuntu/pool/main/libf/libffi/libffi_3.4.6.orig.tar.gz
# bzip2: https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz
# xz: https://mirrors.tuna.tsinghua.edu.cn/debian/pool/main/x/xz-utils/xz-utils_5.8.1.orig.tar.xz
# zlib: https://zlib.net/fossils/zlib-1.3.1.tar.gz
# SQLite: https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz
# certifi: https://pypi.org/pypi/certifi/2025.11.12/json (sdist)
# MPL 2.0: /usr/share/common-licenses/MPL-2.0 from Ubuntu 24.04
checksums=$(cat <<EOF
c30bb24b7f1e9a19b11b55a546434f74e739bb4c271a3e3a80ff4380d49f7adb  $python_source
f8b8f6d52886ff0765f1744736f8b208f9c00fce2b0185a5be7a61aca797b4a9  $module_link_patch
c53a47e5e441c930c3928cf7bf6fb00e5d129b630e0aa873b08258656e7345ec  $openssl_source
719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99  $mutagen_source
71909758f010c82bc99b0abf4ea12012c98962fbf0583c2164f8b84533c2e4da  $crypto_source
9ac790464c1eb2f5ab5809e978a1683e9393131aede72d1b0a0703771d3c6cda  $ffi_source
ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269  $bzip_source
0b54f79df85912504de0b14aec7971e3f964491af1812d83447005807513cd9e  $xz_source
9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23  $zlib_source
a3db587a1b92ee5ddac2f66b3edb41b26f9c867275782d46c3a088977d6a5b18  $sqlite_source
d8ab5478f2ecd78af242878415affce761ca6bc54a22a27e026d7c25357c3316  $ca_source
fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85  $mpl_source
EOF
)
printf '%s\n' "$checksums" | sha256sum --check --strict

mkdir -- "$3"
output=$(realpath -- "$3")
work=$(mktemp -d "${TMPDIR:-/tmp}/android-python-arm64.XXXXXXXX")
trap 'printf "Build files: %s\n" "$work"' EXIT
prefix="$work/prefix"
jobs=${BUILD_JOBS:-$(nproc)}
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
api=29
host=aarch64-linux-android
target_link_flags=-Wl,-z,max-page-size=16384
printf '%s\n' "$checksums" > "$output/source-inputs.sha256"
"$host_python" -c 'import sys, setuptools; print(sys.version); print("setuptools", setuptools.__version__)' > "$output/host-python.txt"

export PATH="$toolchain:$PATH"
export CC="$toolchain/${host}${api}-clang" CXX="$toolchain/${host}${api}-clang++"
export AR="$toolchain/llvm-ar" RANLIB="$toolchain/llvm-ranlib"
export CFLAGS='-O2 -fPIC'
export CPPFLAGS="-I$prefix/include"
export LDFLAGS="-L$prefix/lib $target_link_flags"
export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
unset PKG_CONFIG_SYSROOT_DIR
"$CC" --version > "$output/target-compiler.txt"

for source in "$python_source" "$openssl_source" "$mutagen_source" "$crypto_source" \
    "$ffi_source" "$bzip_source" "$xz_source" "$zlib_source" "$sqlite_source" "$ca_source"; do
    tar -xf "$source" -C "$work"
done
mkdir -p "$prefix/include" "$prefix/lib"

(
    cd -- "$work/openssl-3.5.2"
    unset CFLAGS CPPFLAGS LDFLAGS
    export ANDROID_NDK_ROOT="$ndk"
    perl ./Configure android-arm64 "-D__ANDROID_API__=$api" \
        --prefix="$prefix" --openssldir=/etc/ssl --libdir=lib \
        -fPIC no-shared no-tests no-apps no-module
    make -j "$jobs" build_libs
    make install_dev
    perl configdata.pm --dump > "$output/openssl-config.txt"
)
(
    cd -- "$work/libffi-3.4.6"
    # Ubuntu's Libtool omits LT_SYS_SYMBOL_USCORE. Verify the NDK ELF convention
    # before replacing the unavailable probe in this Android-only build tree.
    printf 'void ffi_symbol_probe(void) {}\n' | "$CC" -x c -c - -o "$work/ffi-symbol-probe.o"
    "$toolchain/llvm-nm" --defined-only "$work/ffi-symbol-probe.o" | grep -Eq ' T ffi_symbol_probe$'
    grep -Fxq 'LT_SYS_SYMBOL_USCORE' configure.ac
    sed -i 's/^LT_SYS_SYMBOL_USCORE$/sys_symbol_underscore=no/' configure.ac
    autoreconf --force --install
    ./configure --host="$host" --prefix="$prefix" --libdir="$prefix/lib" \
        --disable-shared --disable-docs --enable-static
    make -j "$jobs"
    make install
)
(
    cd -- "$work/bzip2-1.0.8"
    make -j "$jobs" CC="$CC" AR="$AR" RANLIB="$RANLIB" CFLAGS="$CFLAGS" libbz2.a
    install -m 644 bzlib.h "$prefix/include/"
    install -m 644 libbz2.a "$prefix/lib/"
)
(
    cd -- "$work/xz-5.8.1"
    ./configure --host="$host" --prefix="$prefix" --disable-shared --enable-static \
        --disable-doc --disable-nls --disable-xz --disable-xzdec --disable-lzmadec \
        --disable-lzmainfo --disable-scripts
    make -j "$jobs"
    make install
)
(
    cd -- "$work/zlib-1.3.1"
    CHOST="$host" ./configure --static --prefix="$prefix"
    make -j "$jobs" libz.a
    make install
)
(
    cd -- "$work/sqlite-autoconf-3500400"
    # The SQLite release notes publish the SHA3-256 digest of the amalgamation.
    "$host_python" -c 'import hashlib, pathlib; assert hashlib.sha3_256(pathlib.Path("sqlite3.c").read_bytes()).hexdigest() == "9145255e83da6529e70121ee4d7a4c88fe83ca4511da0c9ed13d10842df36782"'
    "$CC" -O2 -fPIC -DSQLITE_THREADSAFE=1 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE \
        -DSQLITE_ENABLE_COLUMN_METADATA -c sqlite3.c -o sqlite3.o
    "$AR" rcs "$prefix/lib/libsqlite3.a" sqlite3.o
    install -m 644 sqlite3.h sqlite3ext.h "$prefix/include/"
)

python_src="$work/Python-3.12.11"
python_build="$work/python-build"
# Android's dynamic loader requires an explicit libpython dependency for the
# standard-library extensions loaded with dlopen().
patch --fuzz=0 -p1 -d "$python_src" < "$module_link_patch"
mkdir -- "$python_build"
cat > "$work/android-config.site" <<'EOF'
ac_cv_file__dev_ptmx=yes
ac_cv_file__dev_ptc=no
ac_cv_buggy_getaddrinfo=no
ac_cv_func_wcsftime=no
ac_cv_working_tzset=yes
ac_cv_posix_semaphores_enabled=no
EOF
(
    cd -- "$python_build"
    export CONFIG_SITE="$work/android-config.site"
    export LIBSQLITE3_CFLAGS="-I$prefix/include"
    export LIBSQLITE3_LIBS="$prefix/lib/libsqlite3.a -lm -ldl"
    "$python_src/configure" --build="$("$python_src/config.guess")" --host="$host" \
        --with-build-python="$host_python" --prefix=/usr --enable-shared \
        --without-static-libpython --without-ensurepip --disable-test-modules \
        --with-openssl="$prefix" --with-openssl-rpath=no \
        --enable-loadable-sqlite-extensions
    cp config.log "$output/config.log"
    make -j "$jobs"
    make altinstall DESTDIR="$work/stage"
)

stage="$work/stage/usr"
runtime_lib="$output/usr/lib"
mkdir -p "$runtime_lib"
install -m 755 "$stage/bin/python3.12" "$output/libpython.so"
install -m 755 "$stage/lib/libpython3.12.so.1.0" "$runtime_lib/"
cp -a "$stage/lib/python3.12" "$runtime_lib/"
mkdir -p "$output/usr/etc/tls" "$output/licenses"
install -m 644 "$work/certifi-2025.11.12/certifi/cacert.pem" "$output/usr/etc/tls/cert.pem"
install -m 644 "$work/certifi-2025.11.12/LICENSE" "$output/licenses/certifi-2025.11.12-MPL-2.0.txt"
install -m 644 "$mpl_source" "$output/licenses/MPL-2.0.txt"
find "$runtime_lib/python3.12" -type f -name '*.pyc' -delete
find "$runtime_lib/python3.12" -type d -name __pycache__ -empty -delete
for module in _ssl _hashlib _ctypes _sqlite3 _bz2 _lzma zlib pyexpat; do
    compgen -G "$runtime_lib/python3.12/lib-dynload/$module.*.so" >/dev/null || {
        printf 'Missing Python extension: %s\n' "$module" >&2
        exit 1
    }
done
printf 'Python core staged: %s\n' "$output"

site="$runtime_lib/python3.12/site-packages"
cp -a "$work/mutagen-1.47.0/mutagen" "$site/"
(
    cd -- "$work/pycryptodomex-3.23.0"
    target_config=("$runtime_lib/python3.12/"_sysconfigdata_*.py)
    test "${#target_config[@]}" -eq 1 && test -f "${target_config[0]}"
    _PYTHON_SYSCONFIGDATA_NAME=$(basename -- "${target_config[0]}" .py)
    export _PYTHON_SYSCONFIGDATA_NAME _PYTHON_HOST_PLATFORM=linux-aarch64
    mkdir -- "$work/target-sysconfig"
    cp -- "${target_config[0]}" "$work/target-sysconfig/"
    export PYTHONPATH="$work/target-sysconfig" PYTHONNOUSERSITE=1
    # Prepend target headers before the host setuptools header directory.
    export CFLAGS="-O2 -fPIC -I$python_build -I$python_src/Include"
    export LDSHARED="$CC -shared $target_link_flags"
    "$host_python" -B setup.py build_py --build-lib "$site" \
        build_ext --build-lib "$site" --build-temp "$work/crypto-build" --parallel "$jobs"
)
compgen -G "$site/Cryptodome/Cipher/_raw_aes*.so" >/dev/null

project=$(cd -- "$script_dir/.." && pwd -P)
"$host_python" - "$project" "$output" <<'PY'
from pathlib import Path
from runpy import run_path
import sys

project, output = map(Path, sys.argv[1:])
check_elf = run_path(project / 'prepare-ffmpeg.py')['check_elf']
for path in (output / 'libpython.so', *(output / 'usr/lib').rglob('*.so*')):
    if path.is_file():
        check_elf(path.read_bytes(), 183, str(path.relative_to(output)))
PY

"$toolchain/llvm-readelf" --wide --file-header --program-headers --dynamic \
    "$output/libpython.so" > "$output/libpython.so.elf.txt"
grep -Eq 'Type:[[:space:]]+DYN' "$output/libpython.so.elf.txt"
grep -Fq '/system/bin/linker64' "$output/libpython.so.elf.txt"
for module in "$runtime_lib/python3.12/lib-dynload/"*.so; do
    if ! "$toolchain/llvm-readelf" --dynamic "$module" | grep -F 'Shared library: [libpython3.12.so.1.0]' >/dev/null; then
        printf 'Missing libpython dependency: %s\n' "$module" >&2
        exit 1
    fi
done
(
    cd -- "$output"
    find usr -type f -print0 | sort -z | xargs -0 sha256sum --
    sha256sum libpython.so
) > "$output/SHA256SUMS.txt"
printf 'Verified arm64-v8a ELF ABI and 16 KiB alignment: %s\n' "$output"
