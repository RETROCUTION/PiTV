#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Installing PiTV app =="

TARGET_USER="${PITV_USER:-pi}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

if [[ "$TARGET_USER" != "pi" ]]; then
  echo "This installer currently requires the Raspberry Pi user to be named 'pi'."
  echo "Reason: PiTV scripts and the systemd service still use /home/pi paths."
  echo "Create the OS user as 'pi' for now, or wait for the path-refactor installer."
  exit 1
fi

if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
  echo "Could not find home directory for user: ${TARGET_USER}"
  exit 1
fi

sudo mkdir -p "${TARGET_HOME}/videos"
sudo install -m 0755 "${ROOT_DIR}/app/videolooper.py" "${TARGET_HOME}/videolooper.py"
sudo install -m 0755 "${ROOT_DIR}/app/looperconfig.py" "${TARGET_HOME}/looperconfig.py"
sudo install -m 0755 "${ROOT_DIR}/app/shutdown.py" "${TARGET_HOME}/shutdown.py"
sudo install -m 0644 "${ROOT_DIR}/assets/videos/insertusb.mov" "${TARGET_HOME}/videos/insertusb.mov"
sudo install -m 0644 "${ROOT_DIR}/assets/videos/static.mkv" "${TARGET_HOME}/videos/static.mkv"
sudo chown -R "${TARGET_USER}:${TARGET_USER}" \
  "${TARGET_HOME}/videolooper.py" \
  "${TARGET_HOME}/looperconfig.py" \
  "${TARGET_HOME}/shutdown.py" \
  "${TARGET_HOME}/videos"

sudo mkdir -p /mnt/usb
sudo chown "${TARGET_USER}:${TARGET_USER}" /mnt/usb

# First boot should show the menu. Preserve an existing user config, but do not
# create one during install.
if [[ -f "${TARGET_HOME}/looper_config.json" ]]; then
  backup="${TARGET_HOME}/looper_config.json.before-pitv-install-$(date +%Y%m%d-%H%M%S)"
  sudo cp "${TARGET_HOME}/looper_config.json" "$backup"
  sudo chown "${TARGET_USER}:${TARGET_USER}" "$backup"
  echo "Existing looper_config.json preserved and backed up to:"
  echo "  $backup"
else
  echo "No looper_config.json created; first boot will open the PiTV menu."
fi

sudo install -m 0644 "${ROOT_DIR}/systemd/looper-menu-tty1.service" /etc/systemd/system/looper-menu-tty1.service
sudo systemctl daemon-reload
sudo systemctl disable getty@tty1.service >/dev/null 2>&1 || true
sudo systemctl enable looper-menu-tty1.service

# Give the app user access to video/audio/input devices where available.
for group in audio video input render plugdev; do
  if getent group "$group" >/dev/null 2>&1; then
    sudo usermod -aG "$group" "$TARGET_USER"
  fi
done

echo "PiTV app installed for user ${TARGET_USER}."
echo "Service enabled: looper-menu-tty1.service"
