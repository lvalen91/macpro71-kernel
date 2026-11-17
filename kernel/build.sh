#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 lvalen91
# Build the MacPro7,1 kernel RPM. Usage: ./build.sh [workdir]
# Needs: rpm-build bc flex bison dwarves elfutils-libelf-devel elfutils-devel
#        openssl-devel ncurses-devel perl zstd ccache
set -euo pipefail
KVER=7.3.4
HERE=$(cd "$(dirname "$0")" && pwd)
W=${1:-$PWD/build}
mkdir -p "$W" && cd "$W"
[ -f linux-$KVER.tar.xz ] || curl -fLO https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-$KVER.tar.xz
[ -d linux-$KVER ] || tar xf linux-$KVER.tar.xz
cd linux-$KVER
git init -q 2>/dev/null || true
for p in $(cat "$HERE/patches/t2/series") ; do git apply "$HERE/patches/t2/$p"; done
for p in "$HERE"/patches/local/*.patch; do git apply "$p"; done
cp "$HERE/config" .config
make olddefconfig
# .git and a tag-less tree add "+" to the version
rm -rf .git
export CCACHE_DIR=$W/.ccache
make -j"$(nproc)" CC="ccache gcc" binrpm-pkg \
  RPMOPTS="--define 'install_mod_strip 1' --define '_binary_payload w3T0.zstdio'"
ls rpmbuild/RPMS/x86_64/
