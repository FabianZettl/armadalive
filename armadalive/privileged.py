"""Calls into the root helper (scripts/install-helper.sh) through sudo; no password prompt, no other privileges."""
import os, subprocess, time

HELPER = "/etc/armadalive/armadalive-helper"  # /usr is read-only on Armada, /etc persists


_seen = (0.0, False)


def available(refresh=False):
    """Is the helper installed and may this user run it without a password? Cached for a few seconds."""
    global _seen
    if not refresh and time.monotonic() - _seen[0] < 3:
        return _seen[1]
    ok = os.path.exists(HELPER) and subprocess.run(["sudo", "-n", "-l", HELPER], capture_output=True).returncode == 0
    _seen = (time.monotonic(), ok)
    return ok


def run(*args):
    """Returns an empty string on success, the helper's error message otherwise."""
    try:
        r = subprocess.run(["sudo", "-n", HELPER, *map(str, args)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    return "" if r.returncode == 0 else (r.stderr.strip() or f"helper failed ({r.returncode})")
