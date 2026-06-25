#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_DIR="${1:-${PITV_STAGE_DIR:-/home/pi/pitv-installer-stage}}"

echo "== Staging PiTV installer payload =="
echo "Stage directory: ${STAGE_DIR}"

mkdir -p \
  "${STAGE_DIR}/home/pi/videos" \
  "${STAGE_DIR}/usr/local/bin" \
  "${STAGE_DIR}/usr/local/lib/omxplayer" \
  "${STAGE_DIR}/opt/vc/lib" \
  "${STAGE_DIR}/etc/systemd/system" \
  "${STAGE_DIR}/etc" \
  "${STAGE_DIR}/boot/firmware"

install -m 0755 "${ROOT_DIR}/app/videolooper.py" "${STAGE_DIR}/home/pi/videolooper.py"
install -m 0755 "${ROOT_DIR}/app/looperconfig.py" "${STAGE_DIR}/home/pi/looperconfig.py"
install -m 0755 "${ROOT_DIR}/app/shutdown.py" "${STAGE_DIR}/home/pi/shutdown.py"
install -m 0644 "${ROOT_DIR}/assets/videos/insertusb.mov" "${STAGE_DIR}/home/pi/videos/insertusb.mov"
install -m 0644 "${ROOT_DIR}/assets/videos/static.mkv" "${STAGE_DIR}/home/pi/videos/static.mkv"

install -m 0755 "${ROOT_DIR}/third_party/omxplayer/files/omxplayer" "${STAGE_DIR}/usr/local/bin/omxplayer"
install -m 0755 "${ROOT_DIR}/third_party/omxplayer/files/omxplayer.bin" "${STAGE_DIR}/usr/local/bin/omxplayer.bin"

for lib in "${ROOT_DIR}"/third_party/omxplayer/libs/*; do
  [[ -f "$lib" ]] || continue
  name="$(basename "$lib")"
  case "$name" in
    libc.so.6|libpthread.so.0|libdl.so.2|libm.so.6|librt.so.1|libresolv.so.2)
      continue
      ;;
  esac
  install -m 0644 "$lib" "${STAGE_DIR}/usr/local/lib/omxplayer/$name"
done

for pattern in libbrcm\* libmmal\* libvcos\* libvcsm\* libvchiq\* libopenmaxil\* libbcm_host.so; do
  for lib in "${ROOT_DIR}"/third_party/omxplayer/libs/${pattern}; do
    [[ -f "$lib" ]] || continue
    install -m 0644 "$lib" "${STAGE_DIR}/opt/vc/lib/$(basename "$lib")"
  done
done

install -m 0644 "${ROOT_DIR}/systemd/looper-menu-tty1.service" \
  "${STAGE_DIR}/etc/systemd/system/looper-menu-tty1.service"
install -m 0644 "${ROOT_DIR}/systemd/pitv-quiet-boot.service" \
  "${STAGE_DIR}/etc/systemd/system/pitv-quiet-boot.service"

cat > "${STAGE_DIR}/etc/asound.conf.pitv-example" <<'ASOUND'
pcm.!default {
    type plug
    slave.pcm "hw:0,0"
}

ctl.!default {
    type hw
    card 0
}
ASOUND

cat > "${STAGE_DIR}/boot/config.txt.pitv-example" <<'BOOTCFG'
# PiTV OMXPlayer display path
dtoverlay=vc4-fkms-v3d
disable_splash=1
gpu_mem=128

# Enable PCM5102 Audio
dtoverlay=hifiberry-dac
BOOTCFG

cat > "${STAGE_DIR}/boot/firmware/cmdline.txt.pitv-example" <<'CMDLINE'
console=tty3 quiet splash loglevel=0 logo.nologo vt.global_cursor_default=0
CMDLINE

cat > "${STAGE_DIR}/MANIFEST.txt" <<MANIFEST
PiTV staged installer payload
Generated: $(date)

This is an isolated filesystem preview. It does not install packages, enable
systemd services, modify /boot/config.txt, write /etc/asound.conf, or touch the
live PiTV installation.

Expected live install targets:
  /home/pi/looperconfig.py
  /home/pi/videolooper.py
  /home/pi/shutdown.py
  /home/pi/videos/insertusb.mov
  /home/pi/videos/static.mkv
  /usr/local/bin/omxplayer
  /usr/local/bin/omxplayer.bin
  /usr/local/lib/omxplayer/
  /opt/vc/lib/ Broadcom/MMAL compatibility libraries
  /etc/systemd/system/looper-menu-tty1.service
  /etc/systemd/system/pitv-quiet-boot.service

No looper_config.json is staged. A fresh install should boot into the menu.
MANIFEST

PYTHONPYCACHEPREFIX="${STAGE_DIR}/.pycache" python3 -m py_compile \
  "${STAGE_DIR}/home/pi/looperconfig.py" \
  "${STAGE_DIR}/home/pi/videolooper.py" \
  "${STAGE_DIR}/home/pi/shutdown.py"

echo
echo "Stage complete."
echo "Review files with:"
echo "  find '${STAGE_DIR}' -maxdepth 4 -type f | sort"
