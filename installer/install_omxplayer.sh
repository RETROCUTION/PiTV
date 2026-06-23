#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OMX_DIR="${ROOT_DIR}/third_party/omxplayer"

echo "== Installing custom OMXPlayer =="

if [[ ! -x "${OMX_DIR}/files/omxplayer" && ! -f "${OMX_DIR}/files/omxplayer" ]]; then
  echo "Missing ${OMX_DIR}/files/omxplayer"
  exit 1
fi

if [[ ! -f "${OMX_DIR}/files/omxplayer.bin" ]]; then
  echo "Missing ${OMX_DIR}/files/omxplayer.bin"
  exit 1
fi

sudo install -m 0755 "${OMX_DIR}/files/omxplayer" /usr/local/bin/omxplayer
sudo install -m 0755 "${OMX_DIR}/files/omxplayer.bin" /usr/local/bin/omxplayer.bin

sudo mkdir -p /usr/local/lib/omxplayer
if compgen -G "${OMX_DIR}/libs/*" >/dev/null; then
  # Do not put core glibc runtime libraries in the private OMXPlayer library
  # directory. The launcher prepends this directory to LD_LIBRARY_PATH, and
  # overriding libc/pthread/dl/m/rt from a bundled snapshot is fragile across OS
  # patch levels.
  for lib in "${OMX_DIR}"/libs/*; do
    name="$(basename "$lib")"
    case "$name" in
      libc.so.6|libpthread.so.0|libdl.so.2|libm.so.6|librt.so.1|libresolv.so.2)
        echo "Skipping core system library: $name"
        continue
        ;;
    esac
    sudo install -m 0644 "$lib" "/usr/local/lib/omxplayer/$name"
  done
fi

# Keep Broadcom/MMAL libraries in /opt/vc/lib too because the OMX launcher
# includes that path and older OMXPlayer builds expect it.
sudo mkdir -p /opt/vc/lib
for pattern in libbrcm\* libmmal\* libvcos\* libvcsm\* libvchiq\* libopenmaxil\* libbcm_host.so; do
  for lib in "${OMX_DIR}"/libs/${pattern}; do
    [[ -f "$lib" ]] || continue
    sudo install -m 0644 "$lib" "/opt/vc/lib/$(basename "$lib")"
  done
done

for lib_dir in /usr/local/lib/omxplayer /opt/vc/lib; do
  if [[ -f "${lib_dir}/libvchiq_arm.so.0" && ! -e "${lib_dir}/libvchiq_arm.so" ]]; then
    sudo ln -s libvchiq_arm.so.0 "${lib_dir}/libvchiq_arm.so"
  fi
  if [[ -f "${lib_dir}/libvcos.so.0" && ! -e "${lib_dir}/libvcos.so" ]]; then
    sudo ln -s libvcos.so.0 "${lib_dir}/libvcos.so"
  fi
done

sudo ldconfig

echo "Custom OMXPlayer installed:"
/usr/local/bin/omxplayer --version 2>/dev/null || true
