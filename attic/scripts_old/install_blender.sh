#!/usr/bin/env bash
set -euo pipefail

version="5.2.2"
base="${XDG_DATA_HOME:-$HOME/.local/share}/novel-h3-studio"
url="https://mirrors.aliyun.com/blender/release/Blender5.2"
archive="$base/blender-${version}-linux-x64.tar.xz"
checksum="$base/blender-${version}.sha256"
extract="$base/blender-${version}"

mkdir -p "$base"
if [[ ! -x "$extract/blender" ]]; then
  curl -fL --retry 3 -o "$archive" "$url/blender-${version}-linux-x64.tar.xz"
  curl -fL --retry 3 -o "$checksum" "$url/blender-${version}.sha256"
  grep " blender-${version}-linux-x64.tar.xz$" "$checksum" > "$base/checksum-line.txt"
  (cd "$base" && sha256sum -c checksum-line.txt)
  tar -xJf "$archive" -C "$base"
  mv "$base/blender-${version}-linux-x64" "$extract"
  rm -f "$base/checksum-line.txt" "$archive" "$checksum"
fi

"$extract/blender" --background --factory-startup --python-exit-code 1 --version | head -n 2
