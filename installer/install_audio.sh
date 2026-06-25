#!/usr/bin/env bash
set -euo pipefail

echo "== PiTV audio setup =="

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

enable_hifidac=0

if truthy "${PITV_ENABLE_HIFIDAC:-}"; then
  enable_hifidac=1
elif [[ -t 0 && -z "${PITV_NONINTERACTIVE:-}" ]]; then
  echo
  echo "Are you using a PCM5102 / HiFiBerry DAC-style sound card for analog audio?"
  echo "Choose no if you are using HDMI audio or the Pi 3/Pi 4 headphone jack."
  read -r -p "Enable PCM5102 / HiFiDAC setup? [y/N] " answer
  if truthy "$answer"; then
    enable_hifidac=1
  fi
fi

if [[ "$enable_hifidac" != 1 ]]; then
  echo "Skipping PCM5102 / HiFiDAC setup."
  exit 0
fi

boot_config=""
for candidate in /boot/firmware/config.txt /boot/config.txt; do
  if [[ -f "$candidate" ]]; then
    boot_config="$candidate"
    break
  fi
done

if [[ -z "$boot_config" ]]; then
  echo "Could not find Raspberry Pi boot config.txt."
  echo "Expected /boot/config.txt or /boot/firmware/config.txt."
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
sudo cp "$boot_config" "${boot_config}.pitv-backup-${timestamp}"

if ! grep -Eq '^[[:space:]]*dtoverlay=hifiberry-dac([[:space:]]|$)' "$boot_config"; then
  {
    echo
    echo "# Enable PCM5102 Audio"
    echo "dtoverlay=hifiberry-dac"
  } | sudo tee -a "$boot_config" >/dev/null
  echo "Added dtoverlay=hifiberry-dac to $boot_config"
else
  echo "dtoverlay=hifiberry-dac already present in $boot_config"
fi

if [[ -f /etc/asound.conf ]]; then
  sudo cp /etc/asound.conf "/etc/asound.conf.pitv-backup-${timestamp}"
fi

sudo tee /etc/asound.conf >/dev/null <<'ASOUND'
pcm.!default {
    type plug
    slave.pcm "hw:0,0"
}

ctl.!default {
    type hw
    card 0
}
ASOUND

echo "Wrote /etc/asound.conf for PCM5102 / HiFiDAC through ALSA plughw conversion."
echo "This audio change takes effect after reboot."
