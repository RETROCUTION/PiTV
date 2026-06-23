#!/usr/bin/env bash
set -u

failures=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "[OK]   $label"
  else
    echo "[FAIL] $label"
    failures=$((failures + 1))
  fi
}

check_no_missing_omx_libs() {
  if ! command -v ldd >/dev/null 2>&1; then
    return 1
  fi

  ! LD_LIBRARY_PATH=/usr/local/lib/omxplayer:/opt/vc/lib \
    ldd /usr/local/bin/omxplayer.bin 2>/dev/null | grep -q "not found"
}

echo "== PiTV install verification =="

check "Python 3" command -v python3
check "ffprobe" command -v ffprobe
check "fontconfig fc-match" command -v fc-match
check "console setfont" command -v setfont
check "OMXPlayer wrapper" test -x /usr/local/bin/omxplayer
check "OMXPlayer binary" test -x /usr/local/bin/omxplayer.bin
check "OMXPlayer runtime libraries" check_no_missing_omx_libs
check "PiTV menu" test -x /home/pi/looperconfig.py
check "PiTV playback engine" test -x /home/pi/videolooper.py
check "Insert USB video" test -f /home/pi/videos/insertusb.mov
check "Static video" test -f /home/pi/videos/static.mkv
check "USB mount point" test -d /mnt/usb
check "Systemd unit file" test -f /etc/systemd/system/looper-menu-tty1.service
check "PiTV service enabled" systemctl is-enabled looper-menu-tty1.service

if command -v fc-match >/dev/null 2>&1; then
  echo "Fontconfig default font: $(fc-match | head -n 1)"
fi

if command -v aplay >/dev/null 2>&1; then
  echo
  echo "Audio devices:"
  aplay -l || true
fi

echo
if [[ "$failures" -eq 0 ]]; then
  echo "PiTV verification passed."
else
  echo "PiTV verification found ${failures} issue(s)."
fi

exit "$failures"
