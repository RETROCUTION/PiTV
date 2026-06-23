#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${PITV_INSTALL_LOG:-/tmp/pitv-install.log}"
TOTAL_STEPS=6

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

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

read_first_existing() {
  for path in "$@"; do
    if [[ -r "$path" ]]; then
      tr -d '\0' <"$path"
      return 0
    fi
  done
  return 1
}

detect_pi_model() {
  local model
  model="$(read_first_existing /proc/device-tree/model /sys/firmware/devicetree/base/model 2>/dev/null || true)"
  if [[ -n "$model" ]]; then
    echo "$model"
  else
    echo "Unknown Raspberry Pi"
  fi
}

detect_os_pretty_name() {
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    echo "${PRETTY_NAME:-Unknown Raspberry Pi OS}"
  else
    echo "Unknown Raspberry Pi OS"
  fi
}

bar() {
  local current="$1"
  local total="$2"
  local label="$3"
  local width=24
  local filled=$(( current * width / total ))
  local empty=$(( width - filled ))
  local hashes dashes
  hashes="$(printf "%${filled}s" "" | tr " " "#")"
  dashes="$(printf "%${empty}s" "" | tr " " "-")"
  printf "[%s%s] %d/%d %s" "$hashes" "$dashes" "$current" "$total" "$label"
}

run_stage() {
  local step="$1"
  local label="$2"
  shift 2
  local spin='|/-\'
  local i=0

  printf "\n\n---- [%d/%d] %s ----\n" "$step" "$TOTAL_STEPS" "$label" >>"$LOG_FILE"
  printf "Started: %s\n" "$(date)" >>"$LOG_FILE"

  "$@" >>"$LOG_FILE" 2>&1 &
  local pid=$!

  while kill -0 "$pid" >/dev/null 2>&1; do
    local frame="${spin:$(( i % ${#spin} )):1}"
    printf "\r%s %s" "$(bar "$step" "$TOTAL_STEPS" "$label")" "$frame"
    i=$(( i + 1 ))
    sleep 0.25
  done

  if wait "$pid"; then
    printf "\r%s OK\n" "$(bar "$step" "$TOTAL_STEPS" "$label")"
    printf "Finished: %s\n" "$(date)" >>"$LOG_FILE"
  else
    local code=$?
    printf "\r%s FAILED\n" "$(bar "$step" "$TOTAL_STEPS" "$label")"
    echo
    echo "PiTV install failed during: $label"
    echo "Log file: $LOG_FILE"
    echo
    echo "Recent installer log:"
    tail -80 "$LOG_FILE" 2>/dev/null || true
    exit "$code"
  fi
}

: >"$LOG_FILE"
pi_model="$(detect_pi_model)"
os_name="$(detect_os_pretty_name)"

echo
echo "PiTV Installer"
echo "Detected: $pi_model"
echo "OS: $os_name"
echo "Log: $LOG_FILE"
echo
{
  echo "PiTV installer"
  echo "Detected model: $pi_model"
  echo "Detected OS: $os_name"
  echo "Architecture: $(uname -m)"
  echo
} >>"$LOG_FILE"

enable_hifidac=0
if truthy "${PITV_ENABLE_HIFIDAC:-}"; then
  enable_hifidac=1
elif [[ -t 0 && -z "${PITV_NONINTERACTIVE:-}" ]]; then
  echo
  echo "Are you using a PCM5102 / HiFiBerry DAC-style sound card for analog audio?"
  echo "Choose no if you are using HDMI audio or the Pi 3/Pi 4 headphone jack."
  read -r -p "Enable PCM5102 / HiFiDAC setup? [y/N] " audio_answer
  if truthy "$audio_answer"; then
    enable_hifidac=1
  fi
fi

sudo -v

run_stage 1 "Installing packages" "${ROOT_DIR}/installer/install_packages.sh"
run_stage 2 "Configuring display" "${ROOT_DIR}/installer/install_display_boot.sh"
if [[ "$enable_hifidac" == 1 ]]; then
  run_stage 3 "Configuring audio" env PITV_ENABLE_HIFIDAC=1 PITV_NONINTERACTIVE=1 "${ROOT_DIR}/installer/install_audio.sh"
else
  run_stage 3 "Configuring audio" env PITV_NONINTERACTIVE=1 "${ROOT_DIR}/installer/install_audio.sh"
fi
run_stage 4 "Installing OMXPlayer" "${ROOT_DIR}/installer/install_omxplayer.sh"
run_stage 5 "Installing PiTV" "${ROOT_DIR}/installer/install_pitv.sh"
run_stage 6 "Verifying install" "${ROOT_DIR}/installer/verify_install.sh"

echo
echo "PiTV install complete."
echo "Installer log: $LOG_FILE"
echo
echo "Next steps:"
echo "  1. Reboot the Raspberry Pi."
echo "  2. PiTV will open the menu on tty1."
echo "  3. Choose your display/audio/mode settings, then select START PITV."
echo
echo "Reboot now with:"
echo "  sudo reboot"
