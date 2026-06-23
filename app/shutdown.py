#!/usr/bin/env python3
from gpiozero import Button
from subprocess import check_call
from threading import Timer, Lock
from signal import pause

# ========= Config =========
BUTTON_PIN = 3            # BCM pin (Pin 5 on header). This pin has a pull-up on Pi.
HOLD_SECONDS = 2.0        # Hold duration to trigger shutdown
DOUBLE_WINDOW = 0.6       # Max gap between taps to count as a double-press
BOUNCE_TIME = 0.05        # Debounce for the button (seconds)
# ==========================

# State
_press_count = 0
_double_timer = None
_did_hold = False
_lock = Lock()

def _reset_press_count():
    global _press_count, _double_timer
    with _lock:
        _press_count = 0
        if _double_timer:
            _double_timer.cancel()
            _double_timer = None

def do_shutdown():
    # Long hold → shutdown now
    check_call(['sudo', 'poweroff'])

def do_reboot():
    # Double-press → reboot now
    check_call(['sudo', 'reboot'])

def on_held():
    global _did_hold
    # Mark that this press turned into a hold so release won't trigger double logic
    with _lock:
        _did_hold = True
    do_shutdown()

def on_released():
    global _press_count, _double_timer, _did_hold
    with _lock:
        # If the last press was a hold, ignore this release and clear the flag
        if _did_hold:
            _did_hold = False
            _reset_press_count()
            return

        _press_count += 1
        if _press_count == 1:
            # First tap: start the double-press window
            if _double_timer:
                _double_timer.cancel()
            _double_timer = Timer(DOUBLE_WINDOW, _reset_press_count)
            _double_timer.start()
        elif _press_count == 2:
            # Two taps within the window → reboot
            if _double_timer:
                _double_timer.cancel()
                _double_timer = None
            _press_count = 0
            do_reboot()

def main():
    btn = Button(
        BUTTON_PIN,
        pull_up=True,                # Pin 3 has a hardware pull-up
        bounce_time=BOUNCE_TIME,     # Debounce
        hold_time=HOLD_SECONDS       # Duration to trigger on_held
    )
    btn.when_held = on_held
    btn.when_released = on_released
    pause()  # sleep forever, letting callbacks run

if __name__ == "__main__":
    main()
