# PiTV

PiTV is a Raspberry Pi video looper and lightweight media player built around a
custom OMXPlayer runtime. It is designed to boot into a simple on-device menu,
play from a USB drive, and support both practical exhibition looping and a
more playful TV-style mode.

## Current Status

This project is actively being polished. The current installer target is a
fresh 32-bit Raspberry Pi OS Bookworm Lite install using the `pi` user.

Tested so far:

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Bookworm 32-bit Lite
- PCM5102 / HiFiBerry DAC-style ALSA audio
- USB exFAT media drive
- Custom OMXPlayer with limited OSD and playlist disabled

## Install

On a fresh Raspberry Pi OS Lite install:

```bash
git clone https://github.com/RETROCUTION/PiTV.git
cd PiTV
bash install.sh
sudo reboot
```

The installer sets up:

- PiTV menu and playback scripts
- custom OMXPlayer binary and runtime libraries
- bundled insert-USB and static background videos
- tty1 systemd service
- OMX-compatible FKMS/framebuffer boot configuration
- quiet boot cleanup
- optional PCM5102 / HiFiBerry DAC-style audio setup

After reboot, PiTV should open the menu on the connected display. Configure
your mode, display profile, audio output, USB folders, and playback options,
then select `START PITV`.

## Modes

- **TV Mode**: switches between selected videos while keeping a live-style
  timeline, so videos continue to elapse even when not currently on screen.
- **Looper**: plays selected videos all the way through and loops them.
- **Exhibition**: intended for controlled displays where a user selects a
  specific video or curated folder set.
- **Media Player**: planned as a lightweight browse-and-play mode.

## Notes

PiTV currently expects the Raspberry Pi OS username to be `pi`. Generalized
user/path support is on the polish list.

The custom OMXPlayer must be launched with playlist behavior disabled and
limited OSD enabled. PiTV handles that internally.
