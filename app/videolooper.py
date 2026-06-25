#!/usr/bin/env python3
import os, sys, time, subprocess, random, threading, json, signal, select, tty, termios, hashlib, glob

# ==========================
# USER CONFIGURATION (defaults — may be overridden by looper_config.json)
# ==========================
BASIC_VIDEO_LOOPER     = 0   # Standard HDMI looper
BASIC_VIDEO_LOOPER_CRT = 0   # Same, but --aspect-mode fill
LIVE_TV_HD             = 0   # Live TV global-time looper (HD)
LIVE_TV_CRT            = 1   # Live TV global-time looper with --aspect-mode fill

STATIC_BACKGROUND = 1        # 0=off, 1=on
SHUFFLE_VIDEOS   = 1
CHANNEL_SURFING  = 1
CHANNEL_MIN_SECONDS = 10
CHANNEL_MAX_SECONDS = 20
END_GUARD_SECONDS = 3.0
WRAP_SURF_COALESCE_SECONDS = 1.0
PLAYLIST_RESCAN_SECONDS = 30.0
USB_RECOVERY_FIRST_ATTEMPT_SECONDS = 30.0
USB_RECOVERY_RETRY_SECONDS = 300.0

# NEW: audio output mode: "default" (no -o) or "alsa" (-o alsa)
AUDIO_OUTPUT = "default"

# NEW: selected folders list (written by the config menu). "ROOT" means /mnt/usb itself.
SELECTED_FOLDERS = ["ROOT"]
# ==========================
# END USER CONFIGURATION
# ==========================

FALLBACK_VIDEO = "/home/pi/videos/insertusb.mov"
STATIC_VIDEO   = "/home/pi/videos/static.mkv"
MOUNT_PATH     = "/mnt/usb"
CACHE_FILE     = "/home/pi/video_cache.json"
USB_STATE_DIR_NAME = ".pitv"
USB_DURATION_CACHE_NAME = "video_cache.json"
USB_TV_STATE_NAME = "tv_state.json"
USB_BLACKLIST_NAME = "blacklist.json"
EVENT_LOG      = os.environ.get("PITV_EVENT_LOG", "/home/pi/pitv_playback_events.log")
DIAG_LOG       = os.environ.get("PITV_DIAG_LOG", "/home/pi/pitv_video_diagnostics.log")
VIDEO_FORMATS  = (".mp4", ".mkv", ".mov", ".avi", ".m4v")
CONFIG_PATH    = os.environ.get("LOOPER_CONFIG_PATH", "/home/pi/looper_config.json")
STARTUP_PROBE_SECONDS = 1.0
STARTUP_READY_TIMEOUT_SECONDS = 8.0
STARTUP_FAIL_LIMIT = 2
STATIC_LOOP_GUARD_SECONDS = 2.0
CAPTURE_OMX_OUTPUT = True
OMX_OUTPUT_MAX_LINES = 80
OMX_READY_SIGNALS = ("Playing:", "Video codec", "V:PortSettingsChanged")

OMX_FLAGS_BASE = ["omxplayer", "-a", "--limited-osd", "--font-size", "110"]  # -a disables internal playlist

# --------- apply config file overrides (if present) ----------
def load_apply_config():
    global BASIC_VIDEO_LOOPER, BASIC_VIDEO_LOOPER_CRT, LIVE_TV_HD, LIVE_TV_CRT
    global STATIC_BACKGROUND, SHUFFLE_VIDEOS, CHANNEL_SURFING, CHANNEL_MIN_SECONDS, CHANNEL_MAX_SECONDS
    global AUDIO_OUTPUT, SELECTED_FOLDERS

    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    mode = cfg.get("mode")
    if mode in ("BASIC","BASIC_CRT","LIVE_TV","LIVE_TV_CRT"):
        BASIC_VIDEO_LOOPER     = 1 if mode=="BASIC" else 0
        BASIC_VIDEO_LOOPER_CRT = 1 if mode=="BASIC_CRT" else 0
        LIVE_TV_HD             = 1 if mode=="LIVE_TV" else 0
        LIVE_TV_CRT            = 1 if mode=="LIVE_TV_CRT" else 0

    STATIC_BACKGROUND = 1 if bool(cfg.get("static_background", STATIC_BACKGROUND)) else 0
    SHUFFLE_VIDEOS    = 1 if bool(cfg.get("shuffle_videos", SHUFFLE_VIDEOS)) else 0
    CHANNEL_SURFING   = 1 if bool(cfg.get("channel_surfing", CHANNEL_SURFING)) else 0

    # clamp surf window
    mi = int(cfg.get("channel_min_seconds", CHANNEL_MIN_SECONDS))
    ma = int(cfg.get("channel_max_seconds", CHANNEL_MAX_SECONDS))
    mi = max(5, min(3600, mi))
    ma = max(mi+2, min(3600, ma))
    CHANNEL_MIN_SECONDS, CHANNEL_MAX_SECONDS = mi, ma

    # NEW: audio_output
    ao = str(cfg.get("audio_output", AUDIO_OUTPUT)).strip().lower()
    AUDIO_OUTPUT = "alsa" if ao == "alsa" else "default"

    # NEW: folders list (["ROOT", "folderA", "folderB", ...])
    fol = cfg.get("folders", SELECTED_FOLDERS)
    if isinstance(fol, list) and fol:
        SELECTED_FOLDERS = [str(x) for x in fol]
    else:
        SELECTED_FOLDERS = ["ROOT"]

def active_mode():
    sel = {
        "BASIC": BASIC_VIDEO_LOOPER,
        "BASIC (CRT)": BASIC_VIDEO_LOOPER_CRT,
        "LIVE TV": LIVE_TV_HD,
        "LIVE TV (CRT)": LIVE_TV_CRT
    }
    if sum(sel.values()) != 1:
        return "BASIC"
    return [k for k, v in sel.items() if v][0]

def hms(sec):
    s = max(0, int(sec))
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02}:{m:02}:{s:02}"

def println(msg):
    sys.stdout.write(("\n" + msg) if msg else "\n")
    sys.stdout.flush()

def status(msg):
    sys.stdout.write("\r" + msg + " " * 40)
    sys.stdout.flush()

def log_event(event, **fields):
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
        }
        rec.update(fields)
        with open(EVENT_LOG, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except Exception:
        pass

def log_diag(event, **fields):
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
        }
        rec.update(fields)
        with open(DIAG_LOG, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except Exception:
        pass

def playlist_label(path):
    try:
        return os.path.relpath(path, MOUNT_PATH) if os.path.isabs(path) else path
    except Exception:
        return os.path.basename(path)

def playlist_order_hash(playlist):
    payload = "\n".join(os.path.abspath(p) for p in playlist)
    return hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()[:12]

def log_playlist_order(reason, playlist, channel_index=0, current_path=None, extra=None):
    try:
        files = [playlist_label(p) for p in playlist]
        idx = int(channel_index) % len(playlist) if playlist else None
        rec = {
            "reason": reason,
            "count": len(playlist),
            "order_hash": playlist_order_hash(playlist),
            "channel_index": idx,
            "current_file": playlist_label(current_path) if current_path else (files[idx] if idx is not None else None),
            "files": files,
        }
        if extra:
            rec.update(extra)
        log_event("playlist_order", **rec)
    except Exception:
        pass

def file_size_mb(path):
    try:
        return round(os.path.getsize(path) / (1024 * 1024), 1)
    except Exception:
        return None

# ---------- USB helpers ----------
def ensure_dir(path): os.makedirs(path, exist_ok=True)

def is_usb_connected():
    try:
        return os.path.ismount(MOUNT_PATH) and len(os.listdir(MOUNT_PATH)) > 0
    except Exception:
        return False

def find_usb_partition():
    try:
        for dev in sorted(os.listdir("/dev")):
            if dev.startswith("sd") and dev[-1].isdigit():
                return os.path.join("/dev", dev)
    except Exception:
        pass
    return None

def _read_text(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return ""

def usb_storage_sysfs_devices():
    """Return USB device sysfs dirs that expose a mass-storage interface."""
    devices = []
    try:
        for dev_path in sorted(glob.glob("/sys/bus/usb/devices/*")):
            dev = os.path.basename(dev_path)
            if ":" in dev:
                continue
            for iface_path in glob.glob(os.path.join(dev_path, f"{dev}:*")):
                if _read_text(os.path.join(iface_path, "bInterfaceClass")).lower() == "08":
                    devices.append(dev_path)
                    break
    except Exception:
        pass
    return devices

def rescan_usb_storage():
    for host in sorted(glob.glob("/sys/class/scsi_host/host*")):
        scan = os.path.join(host, "scan")
        try:
            subprocess.run(
                ["sudo", "tee", scan],
                input="- - -\n",
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            pass
    try:
        subprocess.run(["udevadm", "settle", "--timeout=5"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
    except Exception:
        pass

def reset_usb_storage_device(dev_path):
    auth = os.path.join(dev_path, "authorized")
    if not os.path.exists(auth):
        return False
    try:
        subprocess.run(
            ["sudo", "tee", auth],
            input="0\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        time.sleep(1.0)
        subprocess.run(
            ["sudo", "tee", auth],
            input="1\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        return True
    except Exception:
        return False

def attempt_usb_recovery(reason, attempt, missing_seconds):
    dev_before = find_usb_partition()
    storage_devs = usb_storage_sysfs_devices()
    log_event(
        "usb_recovery_attempt",
        reason=reason,
        attempt=attempt,
        missing_seconds=round(missing_seconds, 1),
        block_device=dev_before,
        storage_devices=[os.path.basename(p) for p in storage_devs],
    )

    rescan_usb_storage()
    if mount_usb():
        log_event("usb_recovery_success", reason=reason, attempt=attempt, method="scsi_rescan")
        return True

    reset_any = False
    for dev_path in storage_devs:
        if reset_usb_storage_device(dev_path):
            reset_any = True
            log_event(
                "usb_storage_reset",
                reason=reason,
                attempt=attempt,
                device=os.path.basename(dev_path),
            )
            time.sleep(2.0)
            rescan_usb_storage()
            if mount_usb():
                log_event(
                    "usb_recovery_success",
                    reason=reason,
                    attempt=attempt,
                    method="usb_authorized_reset",
                    device=os.path.basename(dev_path),
                )
                return True

    log_event(
        "usb_recovery_waiting",
        reason=reason,
        attempt=attempt,
        reset_attempted=reset_any,
    )
    return False

def wait_for_usb_restore(reason):
    missing_since = time.monotonic()
    next_recovery = missing_since + USB_RECOVERY_FIRST_ATTEMPT_SECONDS
    attempts = 0
    while True:
        if is_usb_connected() or mount_usb():
            return True
        now = time.monotonic()
        if now >= next_recovery:
            attempts += 1
            if attempt_usb_recovery(reason, attempts, now - missing_since):
                return True
            next_recovery = now + USB_RECOVERY_RETRY_SECONDS
        time.sleep(1)

def mount_usb():
    if os.path.ismount(MOUNT_PATH):
        try:
            if os.listdir(MOUNT_PATH):
                return True
        except Exception:
            pass
        try:
            subprocess.run(["sudo", "umount", "-l", MOUNT_PATH],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    dev = find_usb_partition()
    if not dev: return False
    opts = f"rw,uid={os.getuid()},gid={os.getgid()},umask=000"
    try:
        subprocess.run(
            ["sudo", "mount", "-o", opts, dev, MOUNT_PATH],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.run(
            ["sudo", "mount", dev, MOUNT_PATH],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        return False

def unmount_usb():
    subprocess.run(["sudo", "umount", MOUNT_PATH],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _is_osx_junk(name_lower):
    return (
        name_lower.startswith("._") or
        name_lower == ".ds_store" or
        name_lower.startswith(".")      # skip all dotfiles
    )

def get_video_files():
    """Return sorted list of video files from ROOT and/or selected first-level subfolders."""
    try:
        if not os.path.isdir(MOUNT_PATH):
            return []
        files = []
        seen  = set()

        def add_from_dir(rootdir):
            try:
                for f in os.listdir(rootdir):
                    fl = f.lower()
                    if _is_osx_junk(fl):
                        continue
                    p = os.path.join(rootdir, f)
                    if os.path.isfile(p) and fl.endswith(VIDEO_FORMATS):
                        if p not in seen:
                            files.append(p); seen.add(p)
            except Exception:
                pass

        # Include USB root if selected
        if "ROOT" in SELECTED_FOLDERS:
            add_from_dir(MOUNT_PATH)

        # Include any named first-level folders
        for name in SELECTED_FOLDERS:
            if name == "ROOT":
                continue
            sub = os.path.join(MOUNT_PATH, name)
            if os.path.isdir(sub):
                add_from_dir(sub)

        return sorted(files)
    except Exception:
        return []

def filtered_video_files(files):
    with blacklist_lock:
        keys = set(blacklist_cache.keys())
    if not keys:
        return files
    return [p for p in files if key_for(p) not in keys]

def is_blacklisted(path):
    with blacklist_lock:
        return key_for(path) in blacklist_cache

# ---------- Duration cache (ffprobe) ----------
dur_cache = {}
cache_lock = threading.Lock()
blacklist_cache = {}
blacklist_lock = threading.Lock()
startup_failures = {}
startup_failures_lock = threading.Lock()

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                with cache_lock:
                    dur_cache.update({k: float(v) for k, v in data.items()})
        except Exception:
            pass

def save_cache():
    try:
        with cache_lock:
            data = dict(dur_cache)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def usb_state_dir():
    return os.path.join(MOUNT_PATH, USB_STATE_DIR_NAME)

def usb_cache_file():
    return os.path.join(usb_state_dir(), USB_DURATION_CACHE_NAME)

def usb_tv_state_file():
    return os.path.join(usb_state_dir(), USB_TV_STATE_NAME)

def usb_blacklist_file():
    return os.path.join(usb_state_dir(), USB_BLACKLIST_NAME)

def ensure_usb_state_dir():
    if not os.path.ismount(MOUNT_PATH):
        return False
    try:
        os.makedirs(usb_state_dir(), exist_ok=True)
        return True
    except Exception:
        try:
            subprocess.run(["sudo", "mkdir", "-p", usb_state_dir()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return os.path.isdir(usb_state_dir())
        except Exception:
            return False

def load_usb_cache():
    if not os.path.exists(usb_cache_file()):
        return
    try:
        with open(usb_cache_file(), "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            with cache_lock:
                dur_cache.update({k: float(v) for k, v in data.items()})
    except Exception:
        pass

def write_usb_json(target, data):
    try:
        tmp = target + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            tmp = f"/tmp/{os.path.basename(target)}.{os.getpid()}.tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            subprocess.run(
                ["sudo", "cp", tmp, target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            subprocess.run(
                ["sudo", "chmod", "666", target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            try:
                os.remove(tmp)
            except Exception:
                pass
            return True
        except Exception:
            return False

def save_usb_cache():
    if not ensure_usb_state_dir():
        return
    with cache_lock:
        data = dict(dur_cache)
    write_usb_json(usb_cache_file(), data)

def load_blacklist():
    data = {}
    if os.path.exists(usb_blacklist_file()):
        try:
            with open(usb_blacklist_file(), "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    with blacklist_lock:
        blacklist_cache.clear()
        blacklist_cache.update(data)

def save_blacklist():
    if not ensure_usb_state_dir():
        return False
    with blacklist_lock:
        data = dict(blacklist_cache)
    return write_usb_json(usb_blacklist_file(), data)

def blacklist_video(path, reason, detail=None):
    k = key_for(path)
    rec = {
        "file": os.path.basename(path),
        "path": path,
        "reason": reason,
        "detail": detail,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "size_mb": file_size_mb(path),
        "ext": os.path.splitext(path)[1].lower(),
    }
    with blacklist_lock:
        blacklist_cache[k] = rec
    save_blacklist()
    log_event("video_blacklisted", file=rec["file"], reason=reason, detail=detail)
    log_diag("video_blacklisted", **rec)

def note_startup_failure(path, reason, exit_code=None):
    k = key_for(path)
    with startup_failures_lock:
        startup_failures[k] = startup_failures.get(k, 0) + 1
        count = startup_failures[k]
    log_event("startup_failure", file=os.path.basename(path), reason=reason, exit_code=exit_code, count=count)
    log_diag("startup_failure", file=os.path.basename(path), path=path, reason=reason, exit_code=exit_code, count=count)
    if count >= STARTUP_FAIL_LIMIT:
        blacklist_video(path, "startup_failure", {"exit_code": exit_code, "count": count})
    return count

def load_tv_state():
    if not os.path.exists(usb_tv_state_file()):
        return None
    try:
        with open(usb_tv_state_file(), "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("schema") == 1 else None
    except Exception:
        return None

def save_tv_state(clock_started_at, tv_elapsed_at_save, channel_index, playlist, current_path=None):
    if not ensure_usb_state_dir():
        return False
    data = {
        "schema": 1,
        "clock_started_at": round(float(clock_started_at), 3),
        "tv_elapsed_at_save": round(float(tv_elapsed_at_save), 3),
        "updated_at": round(time.time(), 3),
        "mode": active_mode(),
        "folders": list(SELECTED_FOLDERS),
        "shuffle": bool(SHUFFLE_VIDEOS),
        "channel_index": int(channel_index),
        "current_key": key_for(current_path) if current_path else None,
        "current_file": os.path.basename(current_path) if current_path else None,
        "playlist_count": len(playlist),
        "playlist_order_hash": playlist_order_hash(playlist),
    }
    return write_usb_json(usb_tv_state_file(), data)

def save_all_caches():
    save_cache()
    save_usb_cache()

def key_for(path):
    try:
        st = os.stat(path)
        return f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        return os.path.abspath(path)

def ffprobe_duration(p):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", p],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def preload_durations_ordered(playlist, prime_count=2):
    to_probe_sync, to_probe_bg = [], []
    with cache_lock:
        for i, p in enumerate(playlist):
            k = key_for(p)
            if k not in dur_cache or dur_cache[k] <= 0:
                (to_probe_sync if i < prime_count else to_probe_bg).append((k, p))
    for k, p in to_probe_sync:
        d = ffprobe_duration(p)
        with cache_lock:
            dur_cache[k] = d
    if to_probe_sync:
        save_all_caches()
    def worker(items):
        changed = False
        for k, p in items:
            d = ffprobe_duration(p)
            item_changed = False
            with cache_lock:
                if dur_cache.get(k) != d:
                    dur_cache[k] = d
                    changed = True
                    item_changed = True
            if item_changed:
                save_all_caches()
        if changed:
            save_all_caches()
    if to_probe_bg:
        threading.Thread(target=worker, args=(to_probe_bg,), daemon=True).start()

def get_duration(path):
    with cache_lock:
        return dur_cache.get(key_for(path), 0.0)

# ---------- Keyboard + OMX ----------
def make_flags_for_mode():
    flags = OMX_FLAGS_BASE[:]
    mode = active_mode()
    if "CRT" in mode:
        flags += ["--aspect-mode", "fill"]
    # NEW: audio output selection
    if AUDIO_OUTPUT == "alsa":
        flags += ["-o", "alsa"]
    return flags

def play_omx(file_path, loop=False, pos=None, layer=None, kbd="inherit"):
    """
    kbd:
      - "inherit": omxplayer reads keyboard directly from TTY
      - "swallow": no keyboard (stdin=DEVNULL)
      - "pipe":    we feed keys via proc.stdin
    """
    cmd = make_flags_for_mode()
    if loop: cmd.append("--loop")
    if pos is not None and pos >= 0:
        cmd += ["--pos", str(int(pos))]
    if layer is not None:
        cmd += ["--layer", str(layer)]
    cmd.append(file_path)

    if kbd == "inherit":
        stdin = None
    elif kbd == "swallow":
        stdin = subprocess.DEVNULL
    else:  # "pipe"
        stdin = subprocess.PIPE

    capture_output = CAPTURE_OMX_OUTPUT and os.path.abspath(file_path) != os.path.abspath(STATIC_VIDEO)
    if capture_output:
        cmd = ["stdbuf", "-oL", "-eL"] + cmd
    launch_t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdin=stdin,
        stdout=(subprocess.PIPE if capture_output else subprocess.DEVNULL),
        stderr=(subprocess.STDOUT if capture_output else subprocess.DEVNULL),
        start_new_session=True,
        text=capture_output,
        bufsize=1 if capture_output else -1,
    )
    proc.pitv_launch_ms = round((time.monotonic() - launch_t0) * 1000, 1)
    proc.pitv_ready = threading.Event()
    proc.pitv_ready_ms = None
    if capture_output:
        capture_omx_output(proc, file_path, launch_t0)
    return proc

def capture_omx_output(proc, file_path, launch_t0):
    def worker():
        lines = 0
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                log_diag(
                    "omx_output",
                    file=os.path.basename(file_path),
                    path=file_path,
                    elapsed_ms=round((time.monotonic() - launch_t0) * 1000, 1),
                    line=line[:500],
                )
                if any(signal in line for signal in OMX_READY_SIGNALS):
                    try:
                        proc.pitv_ready_ms = round((time.monotonic() - launch_t0) * 1000, 1)
                        proc.pitv_ready.set()
                    except Exception:
                        pass
                if lines >= OMX_OUTPUT_MAX_LINES:
                    log_diag(
                        "omx_output_truncated",
                        file=os.path.basename(file_path),
                        path=file_path,
                        lines=lines,
                    )
                    break
        except Exception as exc:
            log_diag("omx_output_error", file=os.path.basename(file_path), path=file_path, error=str(exc))
    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        pass

def foreground_layer():
    return 1 if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO) else None

def stop_proc(proc, fast=False, timeout=0.35):
    """Graceful stop by default; kill the whole OMX wrapper/bin process group."""
    if not proc: return 0.0
    stop_t0 = time.monotonic()
    sig = signal.SIGKILL if fast else signal.SIGINT
    try:
        os.killpg(proc.pid, sig)
        if fast:
            try:
                proc.wait(timeout=0.2)
            except Exception:
                pass
            return round((time.monotonic() - stop_t0) * 1000, 1)
        proc.wait(timeout=timeout)
    except Exception:
        pass
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=0.2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return round((time.monotonic() - stop_t0) * 1000, 1)

def kill_static_processes():
    """Best-effort cleanup for any static background OMX wrapper/bin left behind."""
    try:
        out = subprocess.check_output(["pgrep", "-f", STATIC_VIDEO], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return 0
    killed = 0
    for line in out.splitlines():
        try:
            pid = int(line.strip())
        except Exception:
            continue
        if pid == os.getpid():
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
            killed += 1
            continue
        except Exception:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except Exception:
            pass
    return killed

def probe_startup(proc, path, reason, launch_pos):
    def worker():
        time.sleep(STARTUP_PROBE_SECONDS)
        exit_code = proc.poll()
        log_event(
            "startup_probe",
            file=os.path.basename(path),
            ext=os.path.splitext(path)[1].lower(),
            size_mb=file_size_mb(path),
            reason=reason,
            pos=int(launch_pos),
            after_ms=int(STARTUP_PROBE_SECONDS * 1000),
            alive=(exit_code is None),
            exit_code=exit_code,
        )
        log_diag(
            "startup_probe",
            file=os.path.basename(path),
            path=path,
            ext=os.path.splitext(path)[1].lower(),
            size_mb=file_size_mb(path),
            reason=reason,
            pos=int(launch_pos),
            after_ms=int(STARTUP_PROBE_SECONDS * 1000),
            alive=(exit_code is None),
            exit_code=exit_code,
        )
        if exit_code not in (None, 0):
            note_startup_failure(path, "early_exit", exit_code)
    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        pass

# Small helper: only play a file if it exists (for fallback/static)
def safe_play(file_path, **kwargs):
    if file_path and os.path.exists(file_path):
        return play_omx(file_path, **kwargs)
    return None

# ---------- TTY key capture ----------
def setup_tty():
    if sys.stdin.isatty():
        tty.setcbreak(sys.stdin.fileno())

def restore_tty():
    try:
        if sys.stdin.isatty():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, termios.tcgetattr(sys.stdin))
    except Exception:
        pass

def _read_nonblocking(nbytes):
    try:
        if select.select([sys.stdin], [], [], 0)[0]:
            return os.read(sys.stdin.fileno(), nbytes).decode(errors="ignore")
    except Exception:
        pass
    return ""

def read_key(timeout):
    """
    Nonblocking key reader that understands arrow keys.
    Returns:
      'ESC', 'UP', 'DOWN', 'LEFT', 'RIGHT', single characters like 'n','q',' ', etc., or None
    """
    try:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
    except Exception:
        return None
    if not r:
        return None

    c = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
    if not c:
        return None

    if c != "\x1b":  # not ESC, just return the char
        return c

    # Could be bare ESC or start of CSI sequence. Peek briefly.
    seq = _read_nonblocking(2)  # typically '[' + final
    if not seq:
        return "ESC"
    if seq[0] != "[":
        return "ESC"

    final = seq[1:2]
    if final == "A": return "UP"
    if final == "B": return "DOWN"
    if final == "C": return "RIGHT"
    if final == "D": return "LEFT"
    return None

# ---------- BASIC modes (with Python handling ESC/N) ----------
EXIT_REQUESTED = False
LAST_BASIC_PLAYED = None  # remember last file in BASIC mode to prevent back-to-back repeats

def channel_surf_deadline():
    if not CHANNEL_SURFING:
        return None
    return time.monotonic() + random.randint(CHANNEL_MIN_SECONDS, CHANNEL_MAX_SECONDS)

def _forward_arrow(proc, name):
    if not proc or not proc.stdin: return
    try:
        mapping = {
            "LEFT":  "\x1b[D",
            "RIGHT": "\x1b[C",
            "UP":    "\x1b[A",
            "DOWN":  "\x1b[B",
        }
        seq = mapping.get(name)
        if seq:
            proc.stdin.write(seq.encode()); proc.stdin.flush()
    except Exception:
        pass

def _forward_char(proc, ch):
    if not proc or not proc.stdin: return
    try:
        proc.stdin.write(ch.encode()); proc.stdin.flush()
    except Exception:
        pass

def play_one_basic(path):
    """Play single file in BASIC with Python handling keys. ESC exits to menu. N = next (if surfing OFF)."""
    global EXIT_REQUESTED
    println(f"[PLAYING] {os.path.basename(path)}")
    launch_t0 = time.monotonic()
    proc = play_omx(path, loop=False, pos=None, layer=foreground_layer(), kbd="pipe")
    launch_ms = round((time.monotonic() - launch_t0) * 1000, 1)
    log_event(
        "play_start",
        mode=active_mode(),
        file=os.path.basename(path),
        ext=os.path.splitext(path)[1].lower(),
        size_mb=file_size_mb(path),
        reason="basic_loop",
        launch_ms=launch_ms,
        shuffle=bool(SHUFFLE_VIDEOS),
        static=bool(STATIC_BACKGROUND),
        channel_surfing=bool(CHANNEL_SURFING),
    )
    log_diag(
        "play_start",
        mode=active_mode(),
        file=os.path.basename(path),
        path=path,
        ext=os.path.splitext(path)[1].lower(),
        size_mb=file_size_mb(path),
        reason="basic_loop",
        launch_ms=launch_ms,
        shuffle=bool(SHUFFLE_VIDEOS),
        static=bool(STATIC_BACKGROUND),
        channel_surfing=bool(CHANNEL_SURFING),
    )
    probe_startup(proc, path, "basic_loop", 0)
    deadline = channel_surf_deadline()

    forward_chars = set("  pPoOzZxX1234567890-+=")

    while proc.poll() is None:
        k = read_key(0.05)
        if k:
            if k == "ESC" or k in ("q","Q"):
                EXIT_REQUESTED = True
                stop_proc(proc); return None

            if CHANNEL_SURFING:
                pass
            else:
                if k in ("n","N"):
                    stop_proc(proc); return None
                elif k in ("LEFT","RIGHT","UP","DOWN"):
                    _forward_arrow(proc, k)
                elif len(k) == 1 and k in forward_chars:
                    _forward_char(proc, k)

        if not is_usb_connected() and path.startswith(MOUNT_PATH):
            stop_proc(proc); return None

        if deadline and (time.monotonic() >= deadline):
            stop_proc(proc); return None

        time.sleep(0.03)
    return proc

def play_loop_basic():
    global EXIT_REQUESTED, LAST_BASIC_PLAYED
    while True:
        if EXIT_REQUESTED: return
        vids = get_video_files()
        if not vids:
            time.sleep(2); return

        if SHUFFLE_VIDEOS and len(vids) > 1:
            random.shuffle(vids)
            # Guard: avoid starting a new pass with the same file we *just* finished
            if LAST_BASIC_PLAYED in vids and vids[0] == LAST_BASIC_PLAYED:
                # rotate so a different file starts this pass
                for i, p in enumerate(vids):
                    if p != LAST_BASIC_PLAYED:
                        vids = vids[i:] + vids[:i]
                        break

        for v in vids:
            if EXIT_REQUESTED: return
            if not is_usb_connected(): return
            res = play_one_basic(v)
            # remember what actually played, so the next pass won't start with it
            LAST_BASIC_PLAYED = v
            if res is None:
                if EXIT_REQUESTED: return
                continue
        # repeat forever

# ---------- LIVE TV (global time with per-title clocks) ----------
def build_playlist():
    vids = filtered_video_files(get_video_files())
    if SHUFFLE_VIDEOS:
        random.shuffle(vids)
    return vids

def merge_playlist_order(existing_order, discovered_order):
    """Keep the current session order stable, while adding new files safely."""
    if not existing_order:
        return discovered_order
    discovered = set(discovered_order)
    merged = [p for p in existing_order if p in discovered]
    seen = set(merged)
    added = [p for p in discovered_order if p not in seen]
    if SHUFFLE_VIDEOS:
        random.shuffle(added)
    return merged + added

def playlist_diff(existing_order, discovered_order):
    existing = set(existing_order)
    discovered = set(discovered_order)
    added = [p for p in discovered_order if p not in existing]
    removed = [p for p in existing_order if p not in discovered]
    return added, removed

def compute_idx_pos(playlist, elapsed):
    if not playlist:
        return 0, 0
    durations = [get_duration(p) for p in playlist]
    if all(d > 0 for d in durations):
        total = sum(durations)
        e = elapsed % total if total > 0 else elapsed
        for i, d in enumerate(durations):
            if e < d:
                return i, e
            e -= d
        return len(playlist)-1, max(0, e)
    else:
        e = elapsed
        for i, d in enumerate(durations):
            if d <= 0:
                return i, 0
            if e < d:
                return i, e
            e -= d
        return len(playlist)-1, max(0, e)

# NEW: ensure durations are known up-front for stable mapping
def wait_for_all_durations(pl, timeout=60.0):
    """
    Ensure every file in 'pl' has a stable, nonzero duration before Live TV starts.
    Returns True if all known, False on timeout (we proceed anyway).
    """
    start = time.monotonic()
    missing = []
    with cache_lock:
        for p in pl:
            if dur_cache.get(key_for(p), 0.0) <= 0:
                missing.append(p)
    for p in missing:
        d = ffprobe_duration(p)
        with cache_lock:
            dur_cache[key_for(p)] = d

    while time.monotonic() - start < timeout:
        with cache_lock:
            if all(dur_cache.get(key_for(p), 0.0) > 0 for p in pl):
                return True
        time.sleep(0.1)
    return False

def known_duration_count(pl):
    with cache_lock:
        return sum(1 for p in pl if dur_cache.get(key_for(p), 0.0) > 0)

def known_duration_playlist(pl):
    with cache_lock:
        return [p for p in pl if dur_cache.get(key_for(p), 0.0) > 0]

def wait_for_some_durations(pl, min_count=1, timeout=8.0):
    """Wait only long enough to start TV mode; the rest keep probing in the background."""
    if not pl:
        return False
    start = time.monotonic()
    min_count = max(1, min(min_count, len(pl)))
    while time.monotonic() - start < timeout:
        if known_duration_count(pl) >= min_count:
            return True
        time.sleep(0.1)
    return known_duration_count(pl) > 0

def compute_start_offsets(order):
    """Return {path: start_offset_in_concatenated_tape}, and total length."""
    offsets = {}
    total = 0.0
    for p in order:
        offsets[p] = total
        d = max(0.0, get_duration(p))
        total += d
    return offsets, total

def live_tv_loop():
    global EXIT_REQUESTED
    EXIT_REQUESTED = False

    playlist = build_playlist()
    if not playlist:
        println("[ERROR] No videos found."); return
    log_event("tv_mode_start", files=len(playlist), shuffle=bool(SHUFFLE_VIDEOS), surfing=bool(CHANNEL_SURFING))

    # Prime one duration so playback can begin quickly; scan the rest in the background.
    println("[TV] Scanning videos...")
    preload_durations_ordered(playlist, prime_count=1)
    wait_for_some_durations(playlist, min_count=1, timeout=8.0)

    # Use videos with known durations for stable TV timing. More join as probing finishes.
    tv_playlist = known_duration_playlist(playlist)
    if not tv_playlist:
        log_event("tv_mode_error", reason="no_valid_durations")
        println("[ERROR] No valid durations."); return

    # Precompute per-title start_offsets (each title loops independently)
    start_offsets, total_len = compute_start_offsets(tv_playlist)
    if total_len <= 0:
        log_event("tv_mode_error", reason="zero_total_duration")
        println("[ERROR] No valid durations."); return
    known_signature = tuple(tv_playlist)
    log_event("tv_timing_ready", known=len(tv_playlist), total_seconds=round(total_len, 3))

    current_proc = None
    current_path = None
    current_launch_clock_pos = 0.0
    current_launch_duration = 0.0
    current_launch_mono = 0.0
    printed_insert = False
    last_tick = 0.0
    last_state_save = 0.0
    last_playlist_rescan = time.monotonic()

    resume_force_play = False
    resume_path = None
    resume_pos  = 0

    # TV mode keeps a selected channel. Each channel's video position is global elapsed % its duration.
    channel_index = 0
    log_playlist_order("initial_known", tv_playlist, channel_index)
    running = True
    live_anchor = time.monotonic()  # single global clock epoch
    paused_at = 0.0

    tv_state = load_tv_state()
    if tv_state:
        try:
            now_wall = time.time()
            fallback_elapsed = max(0.0, now_wall - float(tv_state.get("clock_started_at", now_wall)))
            saved_elapsed = float(tv_state.get("tv_elapsed_at_save", fallback_elapsed))
            saved_at = float(tv_state.get("updated_at", now_wall))
            offline_delta = now_wall - saved_at
            if 0 <= offline_delta <= 366 * 24 * 3600:
                restored_elapsed = max(0.0, saved_elapsed + offline_delta)
            else:
                restored_elapsed = max(0.0, saved_elapsed)
            live_anchor = time.monotonic() - restored_elapsed
            channel_index = int(tv_state.get("channel_index", 0)) % len(tv_playlist)
            current_key = tv_state.get("current_key")
            if current_key:
                key_map = {key_for(p): i for i, p in enumerate(tv_playlist)}
                if current_key in key_map:
                    channel_index = key_map[current_key]
            log_event(
                "tv_state_restored",
                elapsed=round(restored_elapsed, 3),
                saved_elapsed=round(saved_elapsed, 3),
                offline_delta=round(offline_delta, 3),
                channel_index=channel_index,
                file=os.path.basename(tv_playlist[channel_index]) if tv_playlist else None,
            )
            log_playlist_order("tv_state_restored", tv_playlist, channel_index)
        except Exception:
            log_event("tv_state_ignored")

    def save_current_tv_state(force=False):
        nonlocal last_state_save
        if not tv_playlist:
            return
        now = time.monotonic()
        if not force and (now - last_state_save) < 60:
            return
        elapsed_now = (time.monotonic() - live_anchor) if running else paused_at
        clock_started_at = time.time() - elapsed_now
        selected_path = current_path if current_path in tv_playlist else tv_playlist[channel_index % len(tv_playlist)]
        if save_tv_state(clock_started_at, elapsed_now, channel_index, tv_playlist, selected_path):
            last_state_save = now

    static_proc = None
    static_start_mono = None
    static_duration = 0.0
    if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO):
        static_proc = safe_play(STATIC_VIDEO, loop=True, pos=None, layer=0, kbd="swallow")
        static_start_mono = time.monotonic()
        static_duration = ffprobe_duration(STATIC_VIDEO)

    def static_loop_guard_active(at_time=None):
        if not static_proc or not static_start_mono or static_duration <= (STATIC_LOOP_GUARD_SECONDS * 4):
            return False
        at_time = time.monotonic() if at_time is None else at_time
        phase = (at_time - static_start_mono) % static_duration
        return phase <= STATIC_LOOP_GUARD_SECONDS or (static_duration - phase) <= STATIC_LOOP_GUARD_SECONDS

    def schedule_surf_deadline():
        deadline = channel_surf_deadline()
        if deadline and static_proc and static_duration > (STATIC_LOOP_GUARD_SECONDS * 4):
            phase = (deadline - static_start_mono) % static_duration
            if phase <= STATIC_LOOP_GUARD_SECONDS:
                deadline += (STATIC_LOOP_GUARD_SECONDS - phase) + 0.5
            elif (static_duration - phase) <= STATIC_LOOP_GUARD_SECONDS:
                deadline += (static_duration - phase) + STATIC_LOOP_GUARD_SECONDS + 0.5
        return deadline

    surf_deadline = schedule_surf_deadline()

    # Seen-set ongoing shuffle: reshuffle when all titles have been on-air at least once.
    seen_set = set()

    setup_tty()
    try:
        while True:
            if EXIT_REQUESTED:
                break

            # timekeeping
            elapsed = (time.monotonic() - live_anchor) if running else paused_at

            # Keys: ESC/Q => exit; N/B => move through the current TV order.
            k = read_key(0.05)
            if k:
                if k == "ESC" or k in ("q","Q"):
                    EXIT_REQUESTED = True
                    stop_proc(current_proc)
                    break
                if not CHANNEL_SURFING and tv_playlist and k in ("n", "N", "b", "B"):
                    step = -1 if k in ("b", "B") else 1
                    reason = "manual_b" if step < 0 else "manual_n"
                    channel_index = (channel_index + step) % len(tv_playlist)
                    current_path = None
                    surf_deadline = schedule_surf_deadline()
                    log_event("channel_change", reason=reason, channel_index=channel_index)

            # USB removal handling
            if not is_usb_connected():
                if running:
                    paused_at = time.monotonic() - live_anchor
                    running = False
                if not printed_insert:
                    println("Please insert USB...")
                    printed_insert = True
                    log_event("usb_removed", paused_at=round(paused_at, 3))

                # figure out which title is on-air now to resume there later
                if tv_playlist:
                    channel_index = channel_index % len(tv_playlist)
                    resume_path = tv_playlist[channel_index]
                    resume_dur = float(get_duration(resume_path) or 0.0)
                    if resume_dur <= 0 and resume_path == current_path and current_launch_duration > 0:
                        resume_dur = float(current_launch_duration)
                    resume_pos  = int(paused_at % max(1.0, resume_dur))
                else:
                    resume_path, resume_pos = None, 0

                log_playlist_order(
                    "usb_removed",
                    tv_playlist,
                    channel_index,
                    resume_path,
                    {"paused_at": round(paused_at, 3), "resume_pos": resume_pos},
                )

                stop_proc(current_proc); current_proc = None
                if static_proc:
                    stop_proc(static_proc, fast=True)
                    killed_static = kill_static_processes()
                    log_event("static_background_stopped", reason="usb_removed", killed=killed_static)
                    static_proc = None
                    static_start_mono = None
                fb = None
                if os.path.exists(FALLBACK_VIDEO):
                    fb = safe_play(FALLBACK_VIDEO, loop=True, layer=foreground_layer(), kbd="swallow")

                wait_for_usb_restore("live_tv_usb_removed")
                if fb: stop_proc(fb)
                ensure_usb_state_dir()
                load_usb_cache()
                load_blacklist()
                if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO) and not static_proc:
                    static_proc = safe_play(STATIC_VIDEO, loop=True, pos=None, layer=0, kbd="swallow")
                    static_start_mono = time.monotonic()
                    static_duration = ffprobe_duration(STATIC_VIDEO)
                    log_event("static_background_started", reason="usb_restored")

                discovered_list = build_playlist()
                added, removed = playlist_diff(playlist, discovered_list)
                new_list = merge_playlist_order(playlist, discovered_list)
                if added or removed:
                    log_event(
                        "playlist_files_changed",
                        reason="usb_restored",
                        added_count=len(added),
                        removed_count=len(removed),
                        added=[playlist_label(p) for p in added],
                        removed=[playlist_label(p) for p in removed],
                    )
                if not new_list:
                    time.sleep(1); continue

                preload_durations_ordered(new_list, prime_count=1)
                wait_for_some_durations(new_list, min_count=1, timeout=8.0)
                playlist = new_list
                tv_playlist = known_duration_playlist(playlist)
                start_offsets, total_len = compute_start_offsets(tv_playlist)
                if total_len <= 0:
                    log_event("tv_mode_error", reason="zero_total_duration_after_usb")
                    println("[ERROR] No valid durations after refresh."); return
                known_signature = tuple(tv_playlist)
                # keep the same on-air channel if still present
                if resume_path and resume_path in tv_playlist:
                    channel_index = tv_playlist.index(resume_path)
                    live_anchor = time.monotonic() - paused_at
                    running = True
                    printed_insert = False
                    current_path = None
                    resume_force_play = True
                    surf_deadline = schedule_surf_deadline()
                    log_event("usb_restored", resume=os.path.basename(resume_path), resume_pos=resume_pos)
                else:
                    channel_index = channel_index % len(tv_playlist)
                    live_anchor = time.monotonic() - paused_at
                    running = True
                    printed_insert = False
                    current_path = None
                    surf_deadline = schedule_surf_deadline()
                    log_event("usb_restored", resume=None)

                log_playlist_order(
                    "usb_restored",
                    tv_playlist,
                    channel_index,
                    resume_path,
                    {"known": len(tv_playlist), "total_seconds": round(total_len, 3)},
                )
                seen_set.clear()
                last_playlist_rescan = time.monotonic()
                continue

            if (time.monotonic() - last_playlist_rescan) >= PLAYLIST_RESCAN_SECONDS:
                last_playlist_rescan = time.monotonic()
                discovered_list = build_playlist()
                added, removed = playlist_diff(playlist, discovered_list)
                if added or removed:
                    new_list = merge_playlist_order(playlist, discovered_list)
                    log_event(
                        "playlist_files_changed",
                        reason="active_rescan",
                        added_count=len(added),
                        removed_count=len(removed),
                        added=[playlist_label(p) for p in added],
                        removed=[playlist_label(p) for p in removed],
                    )
                    playlist = new_list
                    preload_durations_ordered(playlist, prime_count=0)
                    log_playlist_order(
                        "active_rescan_pending_durations",
                        playlist,
                        channel_index,
                        current_path,
                        {"known": known_duration_count(playlist)},
                    )

            latest_known = known_duration_playlist(playlist)
            latest_signature = tuple(latest_known)
            if latest_known and latest_signature != known_signature:
                current_name = current_path
                tv_playlist = latest_known
                start_offsets, total_len = compute_start_offsets(tv_playlist)
                if current_name in tv_playlist:
                    channel_index = tv_playlist.index(current_name)
                else:
                    channel_index = channel_index % len(tv_playlist)
                    current_path = None
                known_signature = latest_signature
                save_current_tv_state(force=True)
                log_event("tv_timing_updated", known=len(tv_playlist), total_seconds=round(total_len, 3))
                log_playlist_order(
                    "timing_updated",
                    tv_playlist,
                    channel_index,
                    current_path,
                    {"known": len(tv_playlist), "total_seconds": round(total_len, 3)},
                )

            # Auto channel-surf: change selected channel; global clock keeps running.
            if CHANNEL_SURFING and running and surf_deadline and time.monotonic() >= surf_deadline:
                if static_loop_guard_active():
                    surf_deadline = time.monotonic() + 0.5
                    log_event("static_loop_guard", delay_ms=500)
                    continue
                if tv_playlist:
                    channel_index = (channel_index + 1) % len(tv_playlist)
                    current_path = None
                    log_event("channel_change", reason="auto_surf", channel_index=channel_index)
                surf_deadline = schedule_surf_deadline()

            # Compute current channel position. Every channel advances on the same global clock.
            if tv_playlist:
                channel_index = channel_index % len(tv_playlist)
                path = tv_playlist[channel_index]
                if is_blacklisted(path):
                    log_event("blacklisted_skipped", file=os.path.basename(path))
                    log_diag("blacklisted_skipped", file=os.path.basename(path), path=path)
                    playlist = [p for p in playlist if not is_blacklisted(p)]
                    tv_playlist = [p for p in tv_playlist if not is_blacklisted(p)]
                    if not tv_playlist:
                        log_event("tv_mode_error", reason="all_videos_blacklisted")
                        println("[ERROR] All videos are blacklisted."); return
                    channel_index = channel_index % len(tv_playlist)
                    current_path = None
                    continue
                dur = max(1.0, float(get_duration(path)))
                pos_float = elapsed % dur
                end_guard_applied = False
                if 0 < (dur - pos_float) <= END_GUARD_SECONDS:
                    pos_float = 0.0
                    end_guard_applied = True
                pos = int(pos_float)
            else:
                path, pos, pos_float, dur, end_guard_applied = None, 0, 0.0, 0.0, False

            # Ongoing shuffle: reshuffle as soon as we've featured every title once
            if path:
                seen_set.add(path)
                if SHUFFLE_VIDEOS and len(seen_set) >= len(tv_playlist) and len(tv_playlist) > 1:
                    # Reshuffle but pin the current 'path' on-air.
                    current_name = path
                    random.shuffle(playlist)
                    tv_playlist = known_duration_playlist(playlist)
                    known_signature = tuple(tv_playlist)
                    # Rebuild offsets for new order
                    start_offsets, total_len = compute_start_offsets(tv_playlist)
                    # Keep current program on-air
                    if current_name in tv_playlist:
                        channel_index = tv_playlist.index(current_name)
                    else:
                        channel_index = channel_index % len(tv_playlist)
                    # Make the cross-cycle no-repeat rule explicit.
                    next_index = (channel_index + 1) % len(tv_playlist)
                    if tv_playlist[next_index] == current_name:
                        for i, candidate in enumerate(tv_playlist):
                            if candidate != current_name:
                                tv_playlist[next_index], tv_playlist[i] = tv_playlist[i], tv_playlist[next_index]
                                playlist = tv_playlist[:]
                                known_signature = tuple(tv_playlist)
                                break
                    log_event("shuffle_cycle_reset", files=len(tv_playlist), current=os.path.basename(current_name))
                    log_playlist_order("shuffle_cycle_reset", tv_playlist, channel_index, current_name)
                    seen_set.clear()

            if (
                current_proc is not None and
                current_proc.poll() is None and
                current_path == path
            ):
                ready_event = getattr(current_proc, "pitv_ready", None)
                launch_age = time.monotonic() - current_launch_mono
                if (
                    ready_event is not None and
                    not ready_event.is_set() and
                    launch_age >= STARTUP_READY_TIMEOUT_SECONDS
                ):
                    hung_path = current_path
                    stop_ms = stop_proc(current_proc, timeout=0.2)
                    count = note_startup_failure(hung_path, "startup_hang")
                    log_event(
                        "startup_hang_skip",
                        file=os.path.basename(hung_path),
                        after_ms=int(launch_age * 1000),
                        stop_ms=stop_ms,
                        count=count,
                    )
                    log_diag(
                        "startup_hang_skip",
                        file=os.path.basename(hung_path),
                        path=hung_path,
                        after_ms=int(launch_age * 1000),
                        stop_ms=stop_ms,
                        count=count,
                    )
                    current_proc = None
                    current_path = None
                    if tv_playlist:
                        if is_blacklisted(hung_path):
                            playlist = [p for p in playlist if not is_blacklisted(p)]
                            tv_playlist = [p for p in tv_playlist if not is_blacklisted(p)]
                            if not tv_playlist:
                                log_event("tv_mode_error", reason="all_videos_blacklisted")
                                println("[ERROR] All videos are blacklisted."); return
                            channel_index = channel_index % len(tv_playlist)
                        elif len(tv_playlist) > 1:
                            channel_index = (channel_index + 1) % len(tv_playlist)
                        surf_deadline = schedule_surf_deadline()
                        log_event("channel_change", reason="startup_hang_skip", channel_index=channel_index)
                        continue

            scheduled_wrap_restart = False
            if (
                current_proc is not None and
                current_proc.poll() is None and
                current_path == path and
                current_launch_duration > 0
            ):
                remaining = max(0.0, current_launch_duration - current_launch_clock_pos)
                now = time.monotonic()
                if now - current_launch_mono >= remaining + 0.75:
                    if (
                        CHANNEL_SURFING and running and surf_deadline and tv_playlist and
                        now >= (surf_deadline - WRAP_SURF_COALESCE_SECONDS) and
                        not static_loop_guard_active(now)
                    ):
                        stop_proc(current_proc, timeout=0.2)
                        current_proc = None
                        channel_index = (channel_index + 1) % len(tv_playlist)
                        current_path = None
                        surf_deadline = schedule_surf_deadline()
                        log_event("channel_change", reason="auto_surf_wrap_coalesce", channel_index=channel_index)
                        continue
                    scheduled_wrap_restart = True
                    stop_proc(current_proc, timeout=0.2)
                    current_proc = None

            # (Re)launch player if needed
            need_restart = (current_proc is None) or (current_proc.poll() is not None) or (current_path != path) or resume_force_play or scheduled_wrap_restart
            if need_restart:
                prior_path = current_path
                prior_exit = None if scheduled_wrap_restart else (current_proc.poll() if current_proc is not None else None)
                if scheduled_wrap_restart:
                    launch_reason = "scheduled_wrap_restart"
                elif current_proc is None:
                    launch_reason = "initial"
                elif resume_force_play:
                    launch_reason = "usb_resume"
                elif prior_exit is not None and prior_path == path:
                    launch_reason = "same_channel_restart"
                elif prior_path != path:
                    launch_reason = "channel_change"
                else:
                    launch_reason = "restart"
                stop_ms = stop_proc(current_proc)
                if resume_force_play and path == resume_path:
                    launch_pos = int(resume_pos)
                    current_proc = play_omx(path, loop=False, pos=launch_pos, layer=foreground_layer(), kbd="swallow")
                    current_path = path
                    current_launch_clock_pos = float(launch_pos)
                    resume_force_play = False
                    resume_path = None
                else:
                    launch_pos = int(pos)
                    current_proc = play_omx(path, loop=False, pos=launch_pos, layer=foreground_layer(), kbd="swallow")
                    current_path = path
                    current_launch_clock_pos = float(pos_float)
                current_launch_duration = float(get_duration(current_path) or dur)
                current_launch_mono = time.monotonic()
                launch_ms = getattr(current_proc, "pitv_launch_ms", None)

                dur_here = get_duration(current_path)
                dur_str = hms(int(dur_here)) if dur_here > 0 else "??:??:??"
                println(f"[PLAYING] {os.path.basename(current_path)} @ {hms(int(pos))} / {dur_str}")
                log_event(
                    "play_start",
                    reason=launch_reason,
                    file=os.path.basename(current_path),
                    ext=os.path.splitext(current_path)[1].lower(),
                    size_mb=file_size_mb(current_path),
                    pos=launch_pos,
                    duration=round(float(dur_here), 3) if dur_here else 0,
                    end_guard=end_guard_applied,
                    stop_ms=stop_ms,
                    launch_ms=launch_ms,
                    prior_exit=prior_exit,
                )
                log_diag(
                    "play_start",
                    reason=launch_reason,
                    file=os.path.basename(current_path),
                    path=current_path,
                    ext=os.path.splitext(current_path)[1].lower(),
                    size_mb=file_size_mb(current_path),
                    pos=launch_pos,
                    duration=round(float(dur_here), 3) if dur_here else 0,
                    end_guard=end_guard_applied,
                    stop_ms=stop_ms,
                    launch_ms=launch_ms,
                    prior_exit=prior_exit,
                )
                probe_startup(current_proc, current_path, launch_reason, launch_pos)
                save_current_tv_state(force=(launch_reason != "same_channel_restart"))

                if CHANNEL_SURFING and launch_reason in ("initial", "channel_change", "usb_resume"):
                    surf_deadline = schedule_surf_deadline()

            # status ticker
            now = time.monotonic()
            if now - last_tick >= 1:
                d = get_duration(current_path) if current_path else 0
                d_str = hms(int(d)) if d > 0 else "??:??:??"
                status(f"[LIVE] {os.path.basename(current_path) if current_path else '...'} @ {hms(int(pos))} / {d_str}")
                last_tick = now

            time.sleep(0.05)

    finally:
        try:
            save_current_tv_state(force=True)
        except Exception:
            pass
        stop_proc(current_proc)
        if STATIC_BACKGROUND and static_proc:
            stop_proc(static_proc, fast=True)
        for name in ("omxplayer","omxplayer.bin"):
            subprocess.run(["pkill","-TERM",name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.1)
        for name in ("omxplayer","omxplayer.bin"):
            subprocess.run(["pkill","-KILL",name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        restore_tty()

# ---------- Fallback / static helpers ----------
def play_fallback_until_usb():
    fb = None
    if os.path.exists(FALLBACK_VIDEO):
        fb = safe_play(FALLBACK_VIDEO, loop=True, pos=None, layer=foreground_layer(), kbd="swallow")
    println("Please insert USB...")
    wait_for_usb_restore("startup_fallback")
    ensure_usb_state_dir()
    load_usb_cache()
    load_blacklist()
    if fb: stop_proc(fb)

def play_static_bg_if_needed():
    if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO):
        return safe_play(STATIC_VIDEO, loop=True, pos=None, layer=0, kbd="swallow")
    return None

# ---------- Main ----------
def main():
    ensure_dir(MOUNT_PATH)
    load_apply_config()
    load_cache()
    if is_usb_connected():
        ensure_usb_state_dir()
        load_usb_cache()
        load_blacklist()
        save_usb_cache()

    mode = active_mode()
    extras = []
    if SHUFFLE_VIDEOS: extras.append("Shuffle")
    if CHANNEL_SURFING: extras.append("Channel Surfing")
    if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO): extras.append("Static BG")
    extras_str = f" [{', '.join(extras)}]" if extras else ""
    println(f"=== USB Video Looper ({mode}{extras_str}) ===")

    if not is_usb_connected():
        if not mount_usb():
            play_fallback_until_usb()
    if is_usb_connected():
        ensure_usb_state_dir()
        load_usb_cache()
        load_blacklist()
        save_usb_cache()

    if mode.startswith("LIVE TV"):
        live_tv_loop()
    else:
        # BASIC modes (now support static underlay too)
        setup_tty()
        static_proc = None
        try:
            if STATIC_BACKGROUND and os.path.exists(STATIC_VIDEO):
                static_proc = play_static_bg_if_needed()  # layer 0, kbd swallowed

            insert_proc = None
            if not is_usb_connected():
                insert_proc = safe_play(FALLBACK_VIDEO, loop=True, pos=None, layer=foreground_layer(), kbd="swallow")
                println("Please insert USB...")
            while True:
                if EXIT_REQUESTED: break
                while not is_usb_connected():
                    wait_for_usb_restore("basic_loop_usb_missing")
                ensure_usb_state_dir()
                load_usb_cache()
                load_blacklist()
                if insert_proc:
                    stop_proc(insert_proc); insert_proc = None
                play_loop_basic()
                if EXIT_REQUESTED: break
                unmount_usb()
                insert_proc = safe_play(FALLBACK_VIDEO, loop=True, pos=None, layer=foreground_layer(), kbd="swallow")
                println("Please insert USB...")
        finally:
            if static_proc:
                stop_proc(static_proc, fast=True)
            restore_tty()

if __name__ == "__main__":
    main()
