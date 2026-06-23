#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Configuring PiTV display and quiet boot =="

find_existing_file() {
  for candidate in "$@"; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

backup_file() {
  local path="$1"
  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  sudo cp "$path" "${path}.pitv-backup-${timestamp}"
}

ensure_config_value() {
  local path="$1"
  local key="$2"
  local value="$3"

  if grep -Eq "^[[:space:]]*${key}=" "$path"; then
    sudo sed -i "s|^[[:space:]]*${key}=.*|${key}=${value}|" "$path"
  else
    printf "%s=%s\n" "$key" "$value" | sudo tee -a "$path" >/dev/null
  fi
}

boot_config="$(find_existing_file /boot/firmware/config.txt /boot/config.txt || true)"
cmdline_file="$(find_existing_file /boot/firmware/cmdline.txt /boot/cmdline.txt || true)"

if [[ -z "$boot_config" ]]; then
  echo "Could not find Raspberry Pi boot config.txt."
  exit 1
fi

if [[ -z "$cmdline_file" ]]; then
  echo "Could not find Raspberry Pi cmdline.txt."
  exit 1
fi

backup_file "$boot_config"
backup_file "$cmdline_file"

# OMXPlayer needs the firmware framebuffer/Dispmanx path. Raspberry Pi OS
# Bookworm enables full KMS by default, which prevents this custom OMXPlayer
# build from opening a display layer.
sudo sed -i \
  -e 's/^[[:space:]]*dtoverlay=vc4-kms-v3d/#dtoverlay=vc4-kms-v3d/' \
  -e 's/^[[:space:]]*disable_fw_kms_setup=1/#disable_fw_kms_setup=1/' \
  "$boot_config"

overlay_dir="$(dirname "$boot_config")/overlays"
if [[ -f "${overlay_dir}/vc4-fkms-v3d.dtbo" ]]; then
  if grep -Eq '^[#[:space:]]*dtoverlay=vc4-fkms-v3d([[:space:]]|$)' "$boot_config"; then
    sudo sed -i 's/^[#[:space:]]*dtoverlay=vc4-fkms-v3d.*/dtoverlay=vc4-fkms-v3d/' "$boot_config"
  else
    {
      echo
      echo "# PiTV OMXPlayer display path"
      echo "dtoverlay=vc4-fkms-v3d"
    } | sudo tee -a "$boot_config" >/dev/null
  fi
  echo "Enabled vc4-fkms-v3d overlay for OMXPlayer compatibility."
else
  echo "vc4-fkms-v3d overlay not found; using firmware framebuffer with full KMS disabled."
fi

ensure_config_value "$boot_config" disable_splash 1
ensure_config_value "$boot_config" gpu_mem 128

cmdline="$(sudo cat "$cmdline_file")"
new_tokens=()
tty_console_set=0

for token in $cmdline; do
  case "$token" in
    console=tty[0-9]*)
      if [[ "$tty_console_set" -eq 0 ]]; then
        new_tokens+=("console=tty3")
        tty_console_set=1
      fi
      ;;
    quiet|splash|loglevel=*|logo.nologo|vt.global_cursor_default=*)
      ;;
    *)
      new_tokens+=("$token")
      ;;
  esac
done

if [[ "$tty_console_set" -eq 0 ]]; then
  new_tokens+=("console=tty3")
fi

new_tokens+=("quiet" "splash" "loglevel=0" "logo.nologo" "vt.global_cursor_default=0")
printf "%s\n" "${new_tokens[*]}" | sudo tee "$cmdline_file" >/dev/null

sudo install -m 0644 "${ROOT_DIR}/systemd/pitv-quiet-boot.service" \
  /etc/systemd/system/pitv-quiet-boot.service
sudo systemctl daemon-reload
sudo systemctl enable pitv-quiet-boot.service >/dev/null

if getent passwd pi >/dev/null 2>&1; then
  sudo -u pi touch /home/pi/.hushlogin
fi

echo "Display and quiet-boot configuration complete."
echo "These changes take effect after reboot."
