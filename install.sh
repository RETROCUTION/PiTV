#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -m)" != armv7l && "$(uname -m)" != armv6l && "$(uname -m)" != aarch64 ]]; then
  echo "PiTV installer must be run on Raspberry Pi OS."
  echo "Detected architecture: $(uname -m)"
  exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this installer as the normal pi user, not with sudo:"
  echo "  bash install.sh"
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required."
  exit 1
fi

echo "== PiTV installer =="
echo "This will install PiTV, custom OMXPlayer, dependencies, and the boot service."
echo

"${ROOT_DIR}/installer/install_packages.sh"
"${ROOT_DIR}/installer/install_display_boot.sh"
"${ROOT_DIR}/installer/install_audio.sh"
"${ROOT_DIR}/installer/install_omxplayer.sh"
"${ROOT_DIR}/installer/install_pitv.sh"
"${ROOT_DIR}/installer/verify_install.sh"

echo
echo "PiTV install complete."
echo
echo "Next steps:"
echo "  1. Reboot the Raspberry Pi."
echo "  2. PiTV will open the menu on tty1."
echo "  3. Choose your display/audio/mode settings, then select START PITV."
echo
echo "Reboot now with:"
echo "  sudo reboot"
