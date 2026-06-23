# Vanilla Raspberry Pi OS Install Notes

Goal: start from a clean 32-bit Raspberry Pi OS Lite/headless image, run one
command, and boot into the PiTV menu on the next reboot.

## Supported Target

- Raspberry Pi OS 32-bit Lite/headless.
- Bookworm is the current clean-install validation target.
- The first installer version expects the OS username to be `pi`, because the
  current PiTV scripts and systemd service still use `/home/pi` paths.

## One-Command Install Shape

From a fresh Pi with network enabled:

```bash
git clone https://github.com/RETROCUTION/PiTV.git
cd PiTV
bash install.sh
sudo reboot
```

For now, create the Raspberry Pi OS user as `pi` in Raspberry Pi Imager. Later
we should refactor PiTV paths so the installer can support arbitrary usernames.

## Isolated Installer Staging

On an already-working PiTV system, do **not** run `bash install.sh` just to test
the installer. The real installer writes to live paths such as `/usr/local/bin`,
`/etc/systemd/system`, `/boot/config.txt`, `/etc/asound.conf`, and `/home/pi`.

Use the staging script instead:

```bash
bash installer/stage_install.sh /home/pi/pitv-installer-stage
```

That creates an isolated filesystem preview containing the files the installer
would deploy, without changing the current PiTV install or enabling services.
It also compiles the Python files to catch syntax errors.

This staging check cannot prove OMXPlayer works on a fresh OS, because it does
not install apt packages or run the service. It is a safe payload/layout check.
The final validation still needs a fresh SD card or fresh Raspberry Pi OS image.

After reboot, PiTV should claim tty1 and open the setup/menu interface.

The installer intentionally does **not** create `/home/pi/looper_config.json`.
That makes first boot land in the menu. Once the user selects settings and
chooses `START PITV`, the menu writes the config and later boots can autoplay.

## What The Installer Does

- Installs required apt packages:
  - `python3`
  - `ffmpeg`
  - `dbus`
  - `fontconfig`
  - `fonts-dejavu-core`
  - `fonts-freefont-ttf`
  - `fbset`
  - `kbd`
  - `console-setup`
  - `console-setup-linux`
  - `psmisc`
  - OMXPlayer text/subtitle/font runtime libraries such as freetype, cairo,
    pango, fribidi, harfbuzz, and libass
- Optionally configures PCM5102 / HiFiBerry DAC-style analog audio:
  - appends `dtoverlay=hifiberry-dac` to the Raspberry Pi boot `config.txt`
  - writes `/etc/asound.conf` so ALSA defaults to card `0`
- Installs custom OMXPlayer:
  - `/usr/local/bin/omxplayer`
  - `/usr/local/bin/omxplayer.bin`
  - bundled OMXPlayer libraries under `/usr/local/lib/omxplayer`
  - Broadcom/MMAL libraries mirrored under `/opt/vc/lib`
- Installs PiTV app files:
  - `/home/pi/looperconfig.py`
  - `/home/pi/videolooper.py`
  - `/home/pi/shutdown.py`
  - `/home/pi/videos/insertusb.mov`
  - `/home/pi/videos/static.mkv`
- Creates `/mnt/usb`.
- Installs and enables `looper-menu-tty1.service`.
- Disables `getty@tty1.service` so the PiTV menu owns the display console.
- Runs a verification pass for Python, ffprobe, fontconfig, OMXPlayer, PiTV
  files, the systemd service, and detected audio devices.

## First-Boot Behavior

If `/home/pi/looper_config.json` does not exist, `looperconfig.py` opens the
menu. If the config exists, it starts playback first and returns to the menu
when playback exits.

This supports the desired appliance behavior:

1. Flash a vanilla image.
2. Run installer.
3. Reboot.
4. Configure PiTV from the on-device menu.
5. Start playback.
6. Future boots return to the saved mode.

## Audio Setup Direction

The current app supports:

- `DEFAULT`
- `ALSA`

During install, PiTV asks whether to enable a PCM5102 / HiFiBerry DAC-style
sound card. Say yes for the Pi Zero AV/USB board DAC setup. Say no for HDMI
audio or a Pi 3/Pi 4 headphone jack setup.

The DAC setup adds this to Raspberry Pi `config.txt`:

```text
# Enable PCM5102 Audio
dtoverlay=hifiberry-dac
```

It also writes `/etc/asound.conf`:

```text
pcm.!default {
type hw
card 0
}

ctl.!default {
type hw
card 0
}
```

For the finished installer/menu, this should expand to:

- `AUTO`
- `HDMI / TV`
- `Headphone Jack`
- `Sound Card / DAC`

Internally these should map to OMXPlayer output modes:

- `HDMI / TV` -> `-o hdmi`
- `Headphone Jack` -> `-o local`
- `Sound Card / DAC` -> `-o alsa`
- `AUTO` -> detect Pi model and available ALSA devices

This matters because Pi Zero users may use either HDMI audio or an external
DAC, while Pi 3/Pi 4 users may use HDMI, built-in analog, or a DAC.

## Open Risks

- The current bundled OMXPlayer payload is the known-good binary from the
  working Pi snapshot. Long term, we should either:
  - publish the exact patched source/build recipe, or
  - clearly version the bundled binary as the PiTV OMXPlayer build.
- Bookworm compatibility needs direct testing.
- The installer currently avoids writing system libraries into `/lib`; it uses
  `LD_LIBRARY_PATH` through the OMXPlayer launcher instead. That is safer, but
  must be tested on a fresh image.
