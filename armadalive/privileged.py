"""Calls into the root helper (scripts/install-helper.sh) through sudo; no password prompt, no other privileges."""
import os, subprocess, threading, time

HELPER = "/etc/armadalive/armadalive-helper"  # /usr is read-only on Armada, /etc persists
RELOAD_FAILED = 3  # I keep this status in sync with scripts/armadalive-helper.


_seen = (float("-inf"), False)
_probe_lock = threading.Lock()
_probe_timeout = 2
_probe_generation = 0


def invalidate():
    """Refresh the probe after the app attempts to install or update the helper."""
    global _seen, _probe_generation
    _probe_generation += 1
    _seen = (float("-inf"), _seen[1])


def available(refresh=False):
    """Check whether sudo will permit the installed helper. Call from a worker."""
    global _seen
    started = time.monotonic()
    with _probe_lock:
        if _seen[0] >= started or (not refresh and started - _seen[0] < 3):
            return _seen[1]
        generation = _probe_generation
        try:
            ok = os.path.exists(HELPER) and subprocess.run(
                ["sudo", "-n", "-l", HELPER], capture_output=True, timeout=_probe_timeout).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if generation == _probe_generation:
            _seen = (time.monotonic(), ok)
        return ok


def run(*args):
    """Returns an empty string on success, the helper's error message otherwise."""
    return run_with_status(*args)[1]


def run_with_status(*args):
    """Return (exit status, error). The status is None if sudo could not run or timed out."""
    try:
        r = subprocess.run(["sudo", "-n", HELPER, *map(str, args)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    return r.returncode, "" if r.returncode == 0 else (r.stderr.strip() or f"helper failed ({r.returncode})")
