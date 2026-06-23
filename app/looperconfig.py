#!/usr/bin/env python3
import curses, json, os, sys, time, subprocess

CONFIG_PATH = "/home/pi/looper_config.json"
LOOPER_PATH = "/home/pi/videolooper.py"
MOUNT_PATH  = "/mnt/usb"  # used to list folders for the picker

# ========= Defaults (used for first boot and after "Delete Config") =========
DEFAULTS = {
    "mode": "BASIC",             # BASIC, BASIC_CRT, LIVE_TV, LIVE_TV_CRT
    "static_background": False,  # OFF by default (clean baseline)
    "shuffle_videos": False,     # OFF by default
    "channel_surfing": False,    # OFF by default
    "channel_min_seconds": 10,
    "channel_max_seconds": 20,
    "audio_output": "DEFAULT",   # DEFAULT or ALSA
    "folders": ["ROOT"],         # NEW: which folders to play from (ROOT = USB root)
}

MODES = ["BASIC", "BASIC_CRT", "LIVE_TV", "LIVE_TV_CRT"]
HOME_MODES = ["TV", "LOOPER", "EXHIBITION", "MEDIA PLAYER"]
AUDIO_CHOICES = ["DEFAULT", "ALSA"]
VIDEO_FORMATS = (".mp4", ".mkv", ".mov", ".avi", ".m4v")
USB_STATE_DIR_NAME = ".pitv"
USB_TV_STATE_NAME = "tv_state.json"
HIDDEN_FOLDER_NAMES = {"omxplayerrecent", USB_STATE_DIR_NAME, "system volume information", "chapters"}
USB_CACHE_FOLDERS = ("OMXPlayerRecent", USB_STATE_DIR_NAME)

MODE_LABELS = {
    "BASIC": "EXHIBITION LOOP - HD",
    "BASIC_CRT": "EXHIBITION LOOP - CRT",
    "LIVE_TV": "TV MODE - HD",
    "LIVE_TV_CRT": "TV MODE - CRT",
}

MODE_HELP = {
    "BASIC": "Loop selected videos for galleries, booths, and displays.",
    "BASIC_CRT": "Loop selected videos with CRT-style fill.",
    "LIVE_TV": "Videos keep time like channels on a TV.",
    "LIVE_TV_CRT": "CRT channel-surf TV with videos keeping time.",
}

MODE_PRESETS = {
    "TV": "LIVE_TV_CRT",
    "LOOPER": "BASIC_CRT",
    "EXHIBITION": "BASIC",
}

MODE_DESCRIPTIONS = {
    "TV": "Live timeline video switching.",
    "LOOPER": "Simple repeat playback.",
    "EXHIBITION": "Controlled display playback.",
    "MEDIA PLAYER": "Browse USB videos, music, pictures.",
    "SLIDESHOW": "Image loop for signs and menus.",
}

SURF_MIN_LIMIT = 5
SURF_MAX_LIMIT = 3600
SURF_GAP_MIN  = 2

# Keep the menu width visually stable (will grow if terminal is narrow)
FIXED_BOX_WIDTH = 56
SAFE_MARGIN_X = 3
SAFE_MARGIN_Y = 1
SAFE_MARGIN_BOTTOM = 3

PAIR_NORMAL = 1
PAIR_DIM = 2
PAIR_HILITE = 3
PAIR_ACCENT = 4
PAIR_WARN = 5
PAIR_VERSION = 7

def init_theme():
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(PAIR_NORMAL, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(PAIR_DIM, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(PAIR_HILITE, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(PAIR_ACCENT, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(PAIR_WARN, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(PAIR_VERSION, curses.COLOR_GREEN, curses.COLOR_BLACK)
    except curses.error:
        pass

def attr(pair, flags=0):
    try:
        return curses.color_pair(pair) | flags
    except curses.error:
        return flags

# ---------- Version tag (top-right, minimal) ----------
SHOW_VERSION          = True
VERSION_TEXT          = "v1.9 UI"   # <- change here when you bump version
VERSION_INSET_X       = 8        # columns from right edge (CRT overscan-friendly)
VERSION_INSET_Y       = 2        # rows from top edge
VERSION_COLOR_PAIR_ID = 7        # green on default bg

def draw_version(stdscr):
    if not SHOW_VERSION:
        return
    h, w = stdscr.getmaxyx()
    label = VERSION_TEXT
    y = max(SAFE_MARGIN_Y, VERSION_INSET_Y)
    x = max(SAFE_MARGIN_X, w - len(label) - VERSION_INSET_X)
    try:
        stdscr.addstr(y, x, label, attr(PAIR_VERSION, curses.A_BOLD))
    except curses.error:
        pass

# ---------- Config I/O ----------
def detect_first_boot_audio_output():
    """Return a safe first-boot audio default without overriding saved config."""
    try:
        for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
            if os.path.exists(path):
                with open(path, "rb") as f:
                    model = f.read().decode("utf-8", "ignore").replace("\x00", "").lower()
                if "zero" in model:
                    break
    except Exception:
        pass

    try:
        out = subprocess.check_output(["aplay", "-l"], text=True, stderr=subprocess.DEVNULL).lower()
        if any(token in out for token in ("hifiberry", "pcm5102", "snd_rpi_hifiberry")):
            return "ALSA"
    except Exception:
        pass

    try:
        boot_text = ""
        for path in ("/boot/firmware/config.txt", "/boot/config.txt"):
            if os.path.exists(path):
                with open(path, "r", errors="ignore") as f:
                    boot_text += f.read().lower()
        if "dtoverlay=hifiberry-dac" in boot_text:
            return "ALSA"
    except Exception:
        pass

    return DEFAULTS["audio_output"]

def load_config():
    cfg = dict(DEFAULTS)
    config_exists = os.path.exists(CONFIG_PATH)
    if not config_exists:
        cfg["audio_output"] = detect_first_boot_audio_output()
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    # sanitize
    if cfg.get("mode") not in MODES:
        cfg["mode"] = DEFAULTS["mode"]
    if isinstance(cfg.get("audio_output"), str):
        cfg["audio_output"] = cfg["audio_output"].upper()
    if cfg.get("audio_output") not in AUDIO_CHOICES:
        cfg["audio_output"] = DEFAULTS["audio_output"]
    for k in ("channel_min_seconds","channel_max_seconds"):
        try: cfg[k] = int(cfg[k])
        except Exception: cfg[k] = DEFAULTS[k]
    # folders list
    if not isinstance(cfg.get("folders"), list) or not cfg["folders"]:
        cfg["folders"] = ["ROOT"]
    # clamp
    clamp_surf_pair(cfg)
    return cfg

def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)

def clamp_surf_pair(cfg):
    mi = max(SURF_MIN_LIMIT, min(SURF_MAX_LIMIT, int(cfg["channel_min_seconds"])))
    ma = max(mi + SURF_GAP_MIN, min(SURF_MAX_LIMIT, int(cfg["channel_max_seconds"])))
    cfg["channel_min_seconds"] = mi
    cfg["channel_max_seconds"] = ma

# ---------- UI helpers ----------
def bool_txt(v): return "ON " if v else "OFF"
def nice_mode(name):
    return MODE_LABELS.get(name, name)

def mode_hint(name):
    return MODE_HELP.get(name, "")

def current_home_mode(cfg):
    mode = cfg.get("mode")
    if mode in ("LIVE_TV", "LIVE_TV_CRT"):
        return "TV"
    if mode == "BASIC_CRT":
        return "LOOPER"
    return "EXHIBITION"

def set_home_mode(cfg, home_mode):
    if home_mode in MODE_PRESETS:
        cfg["mode"] = MODE_PRESETS[home_mode]

def display_profile(cfg):
    mode = cfg.get("mode", "")
    return "CRT FILL" if mode.endswith("_CRT") else "HD FIT"

def set_display_profile(cfg, profile):
    mode = cfg.get("mode", "BASIC")
    wants_crt = profile == "CRT FILL"
    if mode.startswith("LIVE_TV"):
        cfg["mode"] = "LIVE_TV_CRT" if wants_crt else "LIVE_TV"
    elif mode.startswith("BASIC"):
        cfg["mode"] = "BASIC_CRT" if wants_crt else "BASIC"

def toggle_display_profile(cfg):
    set_display_profile(cfg, "HD FIT" if display_profile(cfg) == "CRT FILL" else "CRT FILL")

def audio_txt(v):
    # Pad to constant width inside brackets to keep centering stable
    label = "DEFAULT" if v == "DEFAULT" else "ALSA"
    return f"[{label:<7}]"

def selected_folder_summary(cfg):
    fol = cfg.get("folders", ["ROOT"])
    if "ROOT" in fol and len(fol) == 1:
        return "ROOT"
    show = [x for x in fol if x != "ROOT"]
    show.sort()
    if "ROOT" in fol:
        show.insert(0, "ROOT")
    if len(show) <= 3:
        return ", ".join(show)
        return ", ".join(show[:2]) + f", +{len(show)-2}"

def is_usb_mounted():
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

def mount_usb_for_menu():
    if is_usb_mounted():
        return True

    try:
        os.makedirs(MOUNT_PATH, exist_ok=True)
    except Exception:
        pass

    if os.path.ismount(MOUNT_PATH):
        subprocess.run(["sudo", "umount", "-l", MOUNT_PATH],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)

    dev = find_usb_partition()
    if not dev:
        return False

    opts = f"rw,uid={os.getuid()},gid={os.getgid()},umask=000"
    for cmd in (["sudo", "mount", "-o", opts, dev, MOUNT_PATH],
                ["sudo", "mount", dev, MOUNT_PATH]):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return is_usb_mounted()
        except subprocess.CalledProcessError:
            continue
    return False

def count_selected_videos(cfg):
    selected = cfg.get("folders", ["ROOT"])
    count = 0
    try:
        mount_usb_for_menu()
        if not os.path.isdir(MOUNT_PATH):
            return 0

        def count_dir(path):
            total = 0
            try:
                for f in os.listdir(path):
                    fl = f.lower()
                    if _is_osx_junk(fl):
                        continue
                    p = os.path.join(path, f)
                    if os.path.isfile(p) and fl.endswith(VIDEO_FORMATS):
                        total += 1
            except Exception:
                pass
            return total

        if "ROOT" in selected:
            count += count_dir(MOUNT_PATH)
        for name in selected:
            if name == "ROOT":
                continue
            sub = os.path.join(MOUNT_PATH, name)
            if os.path.isdir(sub):
                count += count_dir(sub)
    except Exception:
        pass
    return count

def usb_status_lines(cfg):
    mounted = is_usb_mounted() or mount_usb_for_menu()
    if mounted:
        try:
            fs = subprocess.check_output(["findmnt", "-n", "-o", "FSTYPE", MOUNT_PATH], text=True).strip()
        except Exception:
            fs = "mounted"
        vids = count_selected_videos(cfg)
        return [f"USB: {vids} videos   {fs or 'mounted'}",
                f"Folders: {selected_folder_summary(cfg)}"]
    return ["USB: Not connected", "Insert USB drive"]

def surf_txt(cfg):
    if not cfg["channel_surfing"]:
        return "OFF"
    return f"{cfg['channel_min_seconds']}-{cfg['channel_max_seconds']}s"

def home_rows(cfg):
    rows = []
    for name in HOME_MODES:
        rows.append((name, ""))
    rows.append(("  OPTIONS", ""))
    actions = [("START PITV",""), ("SHUTDOWN","")]
    return rows, actions, 1

def clean_label(label):
    return label.replace("> ", "").replace("*", "").strip()

def mode_config_rows(cfg, edit_field=None, edit_text=""):
    home_mode = current_home_mode(cfg)
    def duration_value(field, value):
        if edit_field == field:
            return (edit_text or "_") + "_"
        return f"{value}"

    if home_mode == "TV":
        rows = [
            ("Folders >", f"{selected_folder_summary(cfg)}"),
            ("Display", f"{display_profile(cfg)}"),
            ("Shuffle", bool_txt(cfg["shuffle_videos"]).strip()),
            ("Static", bool_txt(cfg["static_background"]).strip()),
            ("Channel Surfing", bool_txt(cfg["channel_surfing"]).strip()),
            ("Min Sec", duration_value("channel_min_seconds", cfg["channel_min_seconds"])),
            ("Max Sec", duration_value("channel_max_seconds", cfg["channel_max_seconds"])),
        ]
    else:
        rows = [
            ("Folders >", f"{selected_folder_summary(cfg)}"),
            ("Display", f"{display_profile(cfg)}"),
            ("Shuffle", bool_txt(cfg["shuffle_videos"]).strip()),
            ("Static", bool_txt(cfg["static_background"]).strip()),
        ]
    actions = [(f"START {home_mode}",""), ("BACK","")]
    return rows, actions, 1

def build_rows_main(cfg):
    """Return (settings_rows, action_rows, spacer_rows_count_after_settings)."""
    settings = [
        ("Use Case",           nice_mode(cfg["mode"])),
        ("Static Background",  f"[{bool_txt(cfg['static_background'])}]"),
        ("Shuffle Videos",     f"[{bool_txt(cfg['shuffle_videos'])}]"),
        ("Channel Surfing",    surf_txt(cfg)),
    ]
    if cfg["channel_surfing"]:
        settings += [
            ("Surf Min (sec)", f"[{cfg['channel_min_seconds']:>4}]"),
            ("Surf Max (sec)", f"[{cfg['channel_max_seconds']:>4}]"),
        ]
    settings += [("MORE OPTIONS >","")]
    actions = [("START PITV",""), ("SHUTDOWN","")]
    return settings, actions, 1  # one blank spacer

def build_rows_more(cfg):
    """Return (option_rows, action_rows, spacer_rows_count_after_options)."""
    # Show a compact summary of selected folders
    fol = cfg.get("folders", ["ROOT"])
    if "ROOT" in fol and len(fol) == 1:
        fol_summary = "[ROOT]"
    else:
        # show up to 2 names then “+N”
        show = [x for x in fol if x != "ROOT"]
        show.sort()
        if "ROOT" in fol: show.insert(0, "ROOT")
        if len(show) <= 3:
            fol_summary = "[" + ", ".join(show) + "]"
        else:
            fol_summary = "[" + ", ".join(show[:2]) + f", +{len(show)-2}]"  # compact

    options = [
        ("Audio Output", audio_txt(cfg["audio_output"])),  # DEFAULT / ALSA
        ("VIDEO FOLDERS >", fol_summary),                  # NEW
        ("SHOW IP", ""),
        ("RESET TV POSITION", ""),
        ("DELETE CACHE", ""),
        ("CLEAR USB CACHE", ""),
        ("DELETE CONFIG",""),
    ]
    actions = [("BACK","")]
    return options, actions, 1

def draw_box(stdscr, title, rows_top, rows_bottom, sel_idx, status_lines=None, help_text=None):
    """Compact CRT-safe list UI. Designed for 15x45 composite console output."""
    stdscr.erase()
    init_theme()
    try:
        stdscr.bkgd(" ", attr(PAIR_NORMAL))
    except curses.error:
        pass
    h, w = stdscr.getmaxyx()
    rows = rows_top + rows_bottom
    status = (status_lines or [""])[0]
    left = min(SAFE_MARGIN_X, max(0, w // 10))
    width = max(20, w - left - SAFE_MARGIN_X)
    top = SAFE_MARGIN_Y
    last_row = max(top + 6, h - SAFE_MARGIN_BOTTOM)
    row_start = top + 3
    visible_count = max(3, last_row - row_start)

    if sel_idx < 0:
        sel_idx = 0
    if rows:
        sel_idx = min(sel_idx, len(rows) - 1)

    start = 0
    if sel_idx >= visible_count:
        start = sel_idx - visible_count + 1
    end = min(len(rows), start + visible_count)

    def put(y, text, row_attr=0):
        if y < 0 or y >= h:
            return
        try:
            stdscr.addstr(y, left, text[:width].ljust(width), row_attr)
        except curses.error:
            pass

    put(top, f"PiTV  {VERSION_TEXT}", attr(PAIR_NORMAL, curses.A_BOLD))
    put(top + 1, title[:width], attr(PAIR_ACCENT, curses.A_BOLD))
    put(top + 2, status[:width], attr(PAIR_DIM))

    def format_row(label, value, selected=False):
        marker = ">" if selected else " "
        label = clean_label(str(label))
        value = str(value)
        available = max(8, width - 2)
        if value:
            max_label = max(4, available - len(value) - 1)
            if len(label) > max_label:
                label = label[:max_label - 1] + ">"
            body = label + " " * max(1, available - len(label) - len(value)) + value
        else:
            body = label
        return marker + body[:available]

    y = row_start
    if start > 0:
        put(y, "^ more", attr(PAIR_DIM))
        y += 1
    for idx in range(start, end):
        label, value = rows[idx]
        selected = idx == sel_idx
        row_attr = attr(PAIR_HILITE, curses.A_BOLD) if selected else attr(PAIR_NORMAL)
        put(y, format_row(label, value, selected), row_attr)
        y += 1
    if end < len(rows) and y < last_row:
        put(y, "v more", attr(PAIR_DIM))

    stdscr.refresh()

# ---------- Popups ----------
def popup(stdscr, message, duration=1.0):
    _popup_draw(stdscr, [message], duration=duration, wait_key=False)

def popup_wait_key(stdscr, title, lines):
    _popup_draw(stdscr, lines, title=title, wait_key=True)

def _popup_draw(stdscr, lines, title=None, duration=1.0, wait_key=False):
    h, w = stdscr.getmaxyx()
    inner_lines = lines[:]
    if wait_key:
        inner_lines.append("")
        inner_lines.append("Press any key to close")
    msg_w = max(len(s) for s in inner_lines) if inner_lines else 0
    title_w = len(title) if title else 0
    width  = min(max(max(msg_w, title_w) + 6, 28), w - 2)
    height = max(5, 4 + len(inner_lines))
    top  = max(0, (h - height)//2)
    left = max(0, (w - width)//2)

    try:
        # box bg
        for y in range(height):
            stdscr.addstr(top + y, left, " " * width)

        # border
        stdscr.addstr(top, left, "┌" + "─"*(width-2) + "┐")
        stdscr.addstr(top+height-1, left, "└" + "─"*(width-2) + "┘")
        for y in range(top+1, top+height-1):
            stdscr.addstr(y, left, "│"); stdscr.addstr(y, left+width-1, "│")

        # title (optional)
        if title:
            tx = left + (width - len(title))//2
            stdscr.addstr(top + 1, tx, title, curses.A_BOLD)

        # content
        content_top = top + (2 if title else 1) + 1
        for i, s in enumerate(inner_lines):
            x = left + (width - len(s))//2
            stdscr.addstr(content_top + i, x, s)

        # keep version visible above the popup too
        draw_version(stdscr)
        stdscr.refresh()

        if wait_key:
            stdscr.nodelay(False)
            stdscr.getch()
        else:
            time.sleep(duration)
    except curses.error:
        if wait_key:
            stdscr.nodelay(False); stdscr.getch()
        else:
            time.sleep(duration)

def confirm(stdscr, title, lines):
    """Simple yes/no confirmation for destructive actions."""
    _popup_draw(stdscr, lines + ["", "Press Y to confirm, any other key to cancel"], title=title, duration=0, wait_key=False)
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))

def prompt_number(stdscr, title, current, min_value, max_value):
    """Tiny CRT-safe number prompt. Returns int or None if cancelled."""
    h, w = stdscr.getmaxyx()
    value = str(current)
    left = min(SAFE_MARGIN_X, max(0, w // 10))
    width = max(20, w - left - SAFE_MARGIN_X)
    top = SAFE_MARGIN_Y
    stdscr.nodelay(False)

    while True:
        stdscr.erase()
        try:
            stdscr.bkgd(" ", attr(PAIR_NORMAL))
        except curses.error:
            pass

        def put(y, text, row_attr=0):
            if 0 <= y < h:
                try:
                    stdscr.addstr(y, left, text[:width].ljust(width), row_attr)
                except curses.error:
                    pass

        put(top, "PiTV NUMBER ENTRY", attr(PAIR_NORMAL, curses.A_BOLD))
        put(top + 1, title, attr(PAIR_ACCENT, curses.A_BOLD))
        put(top + 3, f"Value: {value or '_'}", attr(PAIR_HILITE, curses.A_BOLD))
        put(top + 5, f"Range {min_value}-{max_value}", attr(PAIR_DIM))
        put(top + 6, "Enter=OK  Esc=Cancel", attr(PAIR_DIM))
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (27,):
            return None
        if ch in (curses.KEY_ENTER, 10, 13):
            if not value:
                return current
            try:
                number = int(value)
            except Exception:
                number = current
            return max(min_value, min(max_value, number))
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            value = value[:-1]
            continue
        if ord("0") <= ch <= ord("9"):
            if len(value) < 5:
                value += chr(ch)

# ---------- Helpers for folder picker ----------
def _is_osx_junk(name_lower):
    return (
        name_lower.startswith("._") or
        name_lower == ".ds_store" or
        name_lower.startswith(".")
    )

def list_usb_folders():
    """Return ['ROOT', <subdirs...>] from the USB root; only show folders with videos."""
    items = ["ROOT"]
    mount_usb_for_menu()

    def folder_has_videos(path):
        try:
            for name in os.listdir(path):
                fl = name.lower()
                if _is_osx_junk(fl):
                    continue
                p = os.path.join(path, name)
                if os.path.isfile(p) and fl.endswith(VIDEO_FORMATS):
                    return True
        except Exception:
            pass
        return False

    try:
        for f in sorted(os.listdir(MOUNT_PATH)):
            fl = f.lower()
            if _is_osx_junk(fl) or fl in HIDDEN_FOLDER_NAMES:
                continue
            p = os.path.join(MOUNT_PATH, f)
            if os.path.isdir(p) and folder_has_videos(p):
                items.append(f)
    except Exception:
        # if no mount/permission, still present ROOT
        pass
    return items

def folder_picker(stdscr, initial_selected):
    """
    Multi-select UI. Returns a list of names (e.g., ['ROOT','channel_2',...]).
    initial_selected is a list like ['ROOT', 'channel_2'].
    """
    selected = set(initial_selected or ["ROOT"])
    options  = list_usb_folders()
    sel_idx  = 0

    while True:
        # build rows with checkboxes
        rows_top = []
        for name in options:
            mark = "x" if name in selected else " "
            rows_top.append((f"[{mark}] {name}", ""))

        rows_bottom = [("DONE",""), ("BACK","")]
        draw_box(stdscr, "SELECT VIDEO FOLDERS", rows_top, rows_bottom, sel_idx)

        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord('k')):
            sel_idx = (sel_idx - 1) % (len(rows_top) + len(rows_bottom))
        elif ch in (curses.KEY_DOWN, ord('j')):
            sel_idx = (sel_idx + 1) % (len(rows_top) + len(rows_bottom))
        elif ch in (ord('a'), ord('A')):  # select all
            selected = set(options)
        elif ch in (ord('n'), ord('N')):  # select none (but keep ROOT disabled until user picks something else)
            selected = set()
        elif ch in (curses.KEY_ENTER, 10, 13, ord(' ')):
            if sel_idx < len(rows_top):
                # toggle this option
                name = options[sel_idx]
                if name in selected:
                    selected.remove(name)
                else:
                    selected.add(name)
            else:
                # bottom actions
                label = rows_bottom[sel_idx - len(rows_top)][0]
                if label == "DONE":
                    # ensure at least one selection; default to ROOT
                    if not selected:
                        selected = {"ROOT"}
                    return list(sorted(selected, key=lambda s: (s!="ROOT", s.lower())))
                elif label == "BACK":
                    return initial_selected
        elif ch in (27,):  # ESC
            return initial_selected

# ---------- Actions & helpers ----------
def kill_omx_leftovers():
    for name in ("omxplayer","omxplayer.bin"):
        subprocess.run(["pkill","-TERM",name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.15)
    for name in ("omxplayer","omxplayer.bin"):
        subprocess.run(["pkill","-KILL",name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def clear_tty_to_black():
    try:
        sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
        sys.stdout.flush()
    except Exception:
        pass

def restore_cursor():
    try:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
    except Exception:
        pass

def launch_looper_and_wait(stdscr):
    # Hide menu and run looper until it exits (Q/ESC from looper)
    curses.def_prog_mode()
    curses.endwin()
    clear_tty_to_black()

    env = os.environ.copy()
    env["LOOPER_CONFIG_PATH"] = CONFIG_PATH

    try:
        with open(os.devnull, "w") as devnull:
            proc = subprocess.Popen(
                [sys.executable, "-u", LOOPER_PATH],
                stdin=None, stdout=devnull, stderr=devnull, env=env
            )
            proc.wait()
    except Exception as e:
        print(f"[ERROR] Could not start looper: {e}", flush=True)
        time.sleep(2)

    kill_omx_leftovers()
    restore_cursor()
    curses.reset_prog_mode()
    try:
        stdscr.clear(); stdscr.refresh()
    except Exception:
        pass

def shutdown_now(stdscr):
    try: curses.endwin()
    except Exception: pass
    subprocess.run(["/usr/bin/sudo","/sbin/poweroff"], check=False)
    time.sleep(0.5)
    os._exit(0)

def delete_cache():
    try:
        os.remove("/home/pi/video_cache.json")
    except FileNotFoundError:
        pass
    except Exception:
        pass
    try:
        os.sync()
    except Exception:
        try: subprocess.run(["sync"])
        except Exception: pass

def clear_usb_cache():
    removed = []
    for name in USB_CACHE_FOLDERS:
        path = os.path.join(MOUNT_PATH, name)
        if not os.path.isdir(path):
            continue
        try:
            for entry in os.listdir(path):
                p = os.path.join(path, entry)
                if os.path.isfile(p):
                    os.remove(p)
                    removed.append(p)
            if name == "OMXPlayerRecent":
                try:
                    os.rmdir(path)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        os.sync()
    except Exception:
        try: subprocess.run(["sync"])
        except Exception: pass
    return len(removed)

def reset_tv_position():
    path = os.path.join(MOUNT_PATH, USB_STATE_DIR_NAME, USB_TV_STATE_NAME)
    removed = 0
    try:
        os.remove(path)
        removed = 1
    except FileNotFoundError:
        pass
    except Exception:
        try:
            subprocess.run(["sudo", "rm", "-f", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if not os.path.exists(path):
                removed = 1
        except Exception:
            pass
    try:
        os.sync()
    except Exception:
        try: subprocess.run(["sync"])
        except Exception: pass
    return removed

def delete_config(cfg):
    try:
        os.remove(CONFIG_PATH)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    try:
        os.sync()
    except Exception:
        try: subprocess.run(["sync"])
        except Exception: pass
    # Reset in-memory state to baseline
    cfg.clear()
    cfg.update(DEFAULTS)

def get_local_ip_strings():
    # Try hostname -I first
    ips = []
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True).strip()
        ips = [ip for ip in out.split() if ip and ip != "127.0.0.1"]
    except Exception:
        pass

    # Fallback: ip route get 1.1.1.1
    if not ips:
        try:
            out = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True)
            for tok in out.split():
                if tok.count(".") == 3:
                    ips = [tok]; break
        except Exception:
            pass

    # Last resort: python socket trick
    if not ips:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(("8.8.8.8", 80))
            ips = [s.getsockname()[0]]
            s.close()
        except Exception:
            pass

    return ips if ips else ["(no network)"]

# --- run looper automatically if config already exists (no curses at first) ---
def run_looper_blocking_no_curses():
    clear_tty_to_black()
    env = os.environ.copy()
    env["LOOPER_CONFIG_PATH"] = CONFIG_PATH
    try:
        with open(os.devnull, "w") as devnull:
            proc = subprocess.Popen(
                [sys.executable, "-u", LOOPER_PATH],
                stdin=None, stdout=devnull, stderr=devnull, env=env
            )
            proc.wait()
    finally:
        kill_omx_leftovers()
        restore_cursor()

# ---------- Main loop ----------
def run_menu(stdscr):
    cfg = load_config()
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    page = "home"   # "home", "mode", or "more"
    sel  = 0
    duration_edit_field = None
    duration_edit_text = ""

    def finalize_duration_edit():
        nonlocal duration_edit_field, duration_edit_text
        if duration_edit_field and duration_edit_text:
            try:
                cfg[duration_edit_field] = int(duration_edit_text)
            except Exception:
                pass
            clamp_surf_pair(cfg)
        duration_edit_field = None
        duration_edit_text = ""

    while True:
        if page == "home":
            finalize_duration_edit()
            rows_top, rows_bottom, _ = home_rows(cfg)
            draw_box(
                stdscr,
                "SELECT MODE",
                rows_top,
                rows_bottom,
                sel,
                status_lines=usb_status_lines(cfg),
                help_text="Choose what to play.",
            )
            selectable = rows_top + rows_bottom
        elif page == "mode":
            rows_top, rows_bottom, _ = mode_config_rows(cfg, duration_edit_field, duration_edit_text)
            hm = current_home_mode(cfg)
            draw_box(
                stdscr,
                f"MODE: {hm}",
                rows_top,
                rows_bottom,
                sel,
                status_lines=usb_status_lines(cfg),
                help_text=MODE_DESCRIPTIONS.get(hm, ""),
            )
            selectable = rows_top + rows_bottom
        else:
            finalize_duration_edit()
            rows_top, rows_bottom, _ = build_rows_more(cfg)
            draw_box(
                stdscr,
                "OPTIONS / CONFIG",
                rows_top,
                rows_bottom,
                sel,
                status_lines=usb_status_lines(cfg),
                help_text="System tools and maintenance.",
            )
            selectable = rows_top + rows_bottom

        ch = stdscr.getch()
        if ch == -1:
            continue

        # Navigation within selectable rows
        if ch in (curses.KEY_UP, ord('k')):
            finalize_duration_edit()
            sel = (sel - 1) % len(selectable)
        elif ch in (curses.KEY_DOWN, ord('j')):
            finalize_duration_edit()
            sel = (sel + 1) % len(selectable)

        # Inline duration typing on the mode screen.
        elif page == "mode" and ord("0") <= ch <= ord("9"):
            label, _ = selectable[sel]
            clean = clean_label(label)
            field = None
            if clean == "Min Sec":
                field = "channel_min_seconds"
            elif clean == "Max Sec":
                field = "channel_max_seconds"
            if field:
                if duration_edit_field != field:
                    duration_edit_field = field
                    duration_edit_text = ""
                if len(duration_edit_text) < 5:
                    duration_edit_text += chr(ch)
                    try:
                        cfg[field] = int(duration_edit_text)
                    except Exception:
                        pass
            else:
                finalize_duration_edit()
        elif page == "mode" and ch in (curses.KEY_BACKSPACE, 127, 8):
            if duration_edit_field:
                duration_edit_text = duration_edit_text[:-1]
                if duration_edit_text:
                    try:
                        cfg[duration_edit_field] = int(duration_edit_text)
                    except Exception:
                        pass
                else:
                    cfg[duration_edit_field] = DEFAULTS[duration_edit_field]

        # Change values (left/right)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            label, value = selectable[sel]
            clean = clean_label(label)
            step = -1 if ch == curses.KEY_LEFT else 1
            finalize_duration_edit()

            if page == "home":
                continue
            elif page == "mode":
                if clean == "Display":
                    toggle_display_profile(cfg)
                elif clean == "Static":
                    cfg["static_background"] = not cfg["static_background"]
                elif clean == "Shuffle":
                    cfg["shuffle_videos"] = not cfg["shuffle_videos"]
                elif clean == "Channel Surfing":
                    turning_on = not cfg["channel_surfing"]
                    cfg["channel_surfing"] = turning_on
                    clamp_surf_pair(cfg)
                    if not turning_on:
                        rows_top2, rows_bottom2, _ = mode_config_rows(cfg)
                        combined = rows_top2 + rows_bottom2
                        for i2, (lab, _) in enumerate(combined):
                                if lab == "Channel Surfing":
                                    sel = i2
                                    break
                elif clean == "Min Sec":
                    cfg["channel_min_seconds"] += step
                    clamp_surf_pair(cfg)
                elif clean == "Max Sec":
                    cfg["channel_max_seconds"] += step
                    clamp_surf_pair(cfg)

            else:  # page == "more"
                if clean == "Audio Output":
                    i = AUDIO_CHOICES.index(cfg["audio_output"])
                    cfg["audio_output"] = AUDIO_CHOICES[(i + step) % len(AUDIO_CHOICES)]

        # Activate (ENTER)
        elif ch in (curses.KEY_ENTER, 10, 13):
            label, _ = selectable[sel]
            clean = clean_label(label)
            finalize_duration_edit()

            if page == "home":
                if clean in HOME_MODES:
                    if clean in MODE_PRESETS:
                        set_home_mode(cfg, clean)
                        page, sel = "mode", 0
                    else:
                        popup_wait_key(stdscr, clean, [
                            "This mode is on the roadmap.",
                            "For now, TV / Looper / Exhibition are ready."
                        ])
                    continue
                if clean == "OPTIONS":
                    page, sel = "more", 0
                    continue
                if clean == "START PITV":
                    save_config(cfg)                # ONLY here do we write the file
                    launch_looper_and_wait(stdscr)  # returns when looper exits
                    cfg = load_config()             # reload cfg after returning
                    sel = 0
                    continue
                if clean == "SHUTDOWN":
                    if confirm(stdscr, "SHUTDOWN", ["Power off the Raspberry Pi?"]):
                        shutdown_now(stdscr)
                    continue

            elif page == "mode":
                hm = current_home_mode(cfg)
                if clean.startswith("Folders"):
                    new_sel = folder_picker(stdscr, cfg.get("folders", ["ROOT"]))
                    cfg["folders"] = new_sel if new_sel else ["ROOT"]
                    continue
                if clean.startswith("START "):
                    save_config(cfg)
                    launch_looper_and_wait(stdscr)
                    cfg = load_config()
                    page, sel = "home", 0
                    continue
                if clean == "BACK":
                    page, sel = "home", 0
                    continue

            else:  # page == "more"
                if clean.startswith("VIDEO FOLDERS"):
                    new_sel = folder_picker(stdscr, cfg.get("folders", ["ROOT"]))
                    cfg["folders"] = new_sel if new_sel else ["ROOT"]
                    continue
                if clean == "SHOW IP":
                    ips = get_local_ip_strings()
                    lines = [f"IP: {ip}" for ip in ips]
                    popup_wait_key(stdscr, "NETWORK", lines)
                    continue
                if clean == "DELETE CACHE":
                    if confirm(stdscr, "DELETE CACHE", ["Clear saved video duration cache?"]):
                        delete_cache()
                        popup(stdscr, "Cache deleted", 0.9)
                    continue
                if clean == "RESET TV POSITION":
                    if confirm(stdscr, "RESET TV POSITION", ["Start TV Mode from the beginning next time?"]):
                        removed = reset_tv_position()
                        msg = "TV position reset" if removed else "No saved TV position"
                        popup(stdscr, msg, 0.9)
                    continue
                if clean == "CLEAR USB CACHE":
                    if confirm(stdscr, "USB CACHE", ["Clear old PiTV/OMXPlayerRecent files from USB?"]):
                        count = clear_usb_cache()
                        popup(stdscr, f"USB cache cleared ({count})", 0.9)
                    continue
                if clean == "DELETE CONFIG":
                    if confirm(stdscr, "RESET SETTINGS", ["Delete PiTV settings and return to defaults?"]):
                        delete_config(cfg)
                        popup(stdscr, "Config deleted", 0.9)
                    continue
                if clean == "BACK":
                    page, sel = "home", 0
                    continue

        # ESC backs out of submenus, but never resumes playback from the menu.
        elif ch == 27:
            finalize_duration_edit()
            if page in ("mode", "more"):
                page, sel = "home", 0
            else:
                sel = 0

        # Optional: F10 also shuts down (no save)
        elif ch == curses.KEY_F10:
            shutdown_now(stdscr)

def main():
    # If config exists, auto-play first; menu appears after the looper exits.
    if os.path.exists(CONFIG_PATH):
        run_looper_blocking_no_curses()
    # Show menu (first boot without config, or after user exits playback)
    curses.wrapper(run_menu)

if __name__ == "__main__":
    main()
