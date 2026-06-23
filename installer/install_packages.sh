#!/usr/bin/env bash
set -euo pipefail

echo "== Installing PiTV apt packages =="

sudo apt-get update

required_packages=(
  python3
  ffmpeg
  dbus
  fontconfig
  fonts-dejavu-core
  fonts-freefont-ttf
  fbset
  kbd
  console-setup
  console-setup-linux
  psmisc
  util-linux
  mount
  libasound2
  libass9
  libcairo2
  libcairo-gobject2
  libdbus-1-3
  libfontconfig1
  libfreetype6
  libfribidi0
  libharfbuzz0b
  libpango-1.0-0
  libpangocairo-1.0-0
  libpangoft2-1.0-0
  libthai0
)

sudo apt-get install -y "${required_packages[@]}"

if command -v fc-cache >/dev/null 2>&1; then
  sudo fc-cache -f
fi

echo "Apt package install complete."
