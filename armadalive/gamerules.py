"""Remembers a power profile and FPS limit for a game, a whole system, every other game (the base rule) or for when no game runs
(the idle rule), and applies it when that game starts or the last game ends."""
import json, math, os
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import emusettings, persistence

CONFIG = os.path.expanduser("~/.config/armadalive/game_rules.json")


IDLE, BASE = "default:idle", "default:base"   # rule keys that belong to no game


def validate_settings(saved):
    if not isinstance(saved, dict):
        return False
    rules, base = saved.get("rules", {}), saved.get("base", {})
    if not isinstance(rules, dict) or not isinstance(base, dict):
        return False
    if not all(value is None or isinstance(value, str) for value in base.values()):
        return False
    for key, rule in rules.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(rule, dict):
            return False
        if not all(rule.get(field) is None or isinstance(rule.get(field), str) for field in ("profile", "title")):
            return False
        fps, res = rule.get("fps", 0), rule.get("res", 0)
        # Existing rules accept numeric frame limits and numeric text. Resolution
        # values cycle arithmetically; retain finite legacy values outside the UI list.
        if fps is not None and not isinstance(fps, (int, float, str)):
            return False
        try:
            if fps:
                int(fps)
        except (ValueError, OverflowError):
            return False
        if not isinstance(res, (int, float)) or (isinstance(res, float) and not math.isfinite(res)):
            return False
    return True


class GameRules(persistence.OwnerWriter, QObject):
    changed = Signal()
    notice = Signal(str, str)   # saved | removed | loaded | failed, and what it was about

    def __init__(self, nowplaying, gamescope, system):
        super().__init__()
        self._np, self._gs, self._sys = nowplaying, gamescope, system
        saved = persistence.read_json(CONFIG, validate_settings, {})
        self._saved = saved
        self._rules, self._on = saved.get("rules", {}), bool(saved.get("enabled", True))
        self._base = saved.get("base", {})
        self._check_deferred = False
        self._applied, self._loaded = "", ""
        self._pending_rule = None
        self.history = None      # set by the app: lets a rule show the name of its game, not only the key
        nowplaying.changed.connect(self._check)
        system.profileFinished.connect(self._profile_finished)
        gamescope.fpsLimitFinished.connect(self._fps_finished)
        system.profileRequested.connect(self._profile_requested)
        gamescope.fpsLimitRequested.connect(self._fps_requested)

    @Property("QVariant", notify=changed)
    def state(self):
        cur = self._np.state
        return dict(enabled=self._on, rules=sorted((dict(v, key=k, **self._describe(k, v)) for k, v in self._rules.items()), key=lambda r: (r["kind"], r["name"].lower())),
                    gameKey=self._game_key(cur), systemKey=self._system_key(cur), resOk=cur.get("system") in emusettings.SPECS,
                    idleKey=IDLE, baseKey=BASE, loaded=self._loaded, writesPaused=self._writes_paused)

    def _describe(self, key, rule):
        """What the rules list shows for a key: its kind and the name of the game or system, never only the Steam id."""
        if key in (IDLE, BASE):
            return dict(kind="idle" if key == IDLE else "base", name="")
        kind, _, rest = key.partition(":")
        if kind == "game":
            return dict(kind="game", name=rule.get("title") or (self.history.title_of(rest) if self.history else "") or rest)
        return dict(kind="system", name=rest)

    @staticmethod
    def _game_key(state):
        return f"game:{state['key']}" if state.get("key") else ""

    @staticmethod
    def _system_key(state):
        return f"system:{state['system']}" if state.get("system") and state.get("kind") == "game" else ""

    def pauseWrites(self, *, restoring=False):
        super().pauseWrites(restoring=restoring)
        # Emulator originals can change on the owner thread between explicit
        # rule edits. Persist them before backup captures the local rollback state.
        snapshot = dict(self._saved, enabled=self._on, rules=self._rules, base=self._base)
        try:
            with open(CONFIG) as stream:
                if json.load(stream) == snapshot:
                    return
        except FileNotFoundError:
            if not self._saved and not self._rules and not self._base and self._on:
                return
        except (ValueError, RecursionError):
            pass
        self._save()

    def _save(self):
        saved = dict(self._saved, enabled=self._on, rules=self._rules, base=self._base)
        if not validate_settings(saved):
            raise ValueError("invalid game rules")
        persistence.write_json(CONFIG, saved, validate=validate_settings, indent=1,
                               follow_symlinks=True, require_writable=True, allow_nan=True)
        self.changed.emit()

    @staticmethod
    def _label(key, cur):
        if key == IDLE:
            return "idle"
        if key == BASE:
            return "base"
        return cur.get("title") or key.split(":", 1)[1] if key.startswith("game:") else key.split(":", 1)[1]

    @Slot(str)
    def toggle(self, scope):
        """Save the current profile and FPS limit for this game, system, as the idle or base rule, or forget the rule if there is one."""
        if self._writes_paused:
            return
        cur = self._np.state
        key = {"game": self._game_key(cur), "system": self._system_key(cur), "idle": IDLE, "base": BASE}.get(scope, "")
        if not key:
            return
        if key in self._rules:
            del self._rules[key]
            self._cancel_pending_rule(key)
            code = "removed"
        else:
            self._rules[key] = dict(profile=self._sys.stats.get("profile", ""), fps=self._gs.state.get("limit", 0))
            if scope == "game" and cur.get("title"):
                self._rules[key]["title"] = cur["title"]
            code = "saved"
        self._save()
        self.notice.emit(code, self._label(key, cur) + (f" · {self._summary(self._rules[key])}" if code == "saved" else ""))

    @staticmethod
    def _summary(rule):
        return (rule.get("profile") or "–") + (f", {rule['fps']} FPS" if rule.get("fps") else "")

    @Slot()
    def cycleRes(self):
        """Step this game's render resolution through off, 1x ... 5x; a game without a rule gets one that only holds the resolution."""
        if self._writes_paused:
            return
        key = self._game_key(self._np.state)
        if not key or self._np.state.get("system") not in emusettings.SPECS:
            return
        rule = self._rules.setdefault(key, dict(profile="", fps=0))
        if self._np.state.get("title"):
            rule["title"] = self._np.state["title"]
        rule["res"] = (rule.get("res", 0) + 1) % (emusettings.MAX + 1)
        self._save()

    @Slot(str)
    def remove(self, key):
        if self._writes_paused:
            return
        if self._rules.pop(key, None) is not None:
            self._cancel_pending_rule(key)
            self._save()
            self.notice.emit("removed", self._label(key, self._np.state))

    @Slot(bool)
    def setEnabled(self, on):
        if self._writes_paused:
            return
        self._on = bool(on)
        if not self._on:
            self._cancel_pending_rule()
        self._save()

    def _emulator(self, cur):
        """Just before a game starts (while it is selected in ES-DE) its emulator gets the saved resolution; a game without one
        gets back what the emulator had before. shortcut: only the first override remembers the original value."""
        system = cur.get("system")
        if cur.get("kind") != "game" or cur.get("playing") or system not in emusettings.SPECS:
            return
        rule = self._rules.get(self._game_key(cur)) or self._rules.get(self._system_key(cur)) or {}
        if rule.get("res"):
            if system not in self._base:
                self._base[system] = emusettings.read(system)
            if self._base[system] is not None:
                emusettings.write(system, rule["res"])
        elif self._base.get(system) is not None:
            emusettings.write(system, self._base.pop(system))

    def _apply(self, key, label):
        rule = self._rules[key]
        self._cancel_pending_rule()
        detail = f"{label} · {self._summary(rule)}"
        requests = {}
        if rule.get("profile"):
            requests["profile"] = self._sys.setProfile(rule["profile"])
        if rule.get("fps"):
            requests["fps"] = self._gs.setFpsLimit(int(rule["fps"]))
        self._pending_rule = (key, requests, set(requests), detail) if requests else None
        if self._loaded:
            self._loaded = ""
            self.changed.emit()
        # Resolution-only rules retain their existing preparation path in _emulator.
        if not requests:
            self._show_loaded(detail)

    def _show_loaded(self, detail):
        self._loaded = detail
        self.changed.emit()
        self.notice.emit("loaded", detail)

    def _cancel_pending_rule(self, key=None):
        if self._pending_rule is None:
            return
        origin, requests, _, _ = self._pending_rule
        if key is not None and key != origin:
            return
        self._pending_rule = None
        # Cancel waiting requests owned by this rule. Dispatched writes finish.
        if "profile" in requests:
            self._sys.cancelProfile(requests["profile"])
        if "fps" in requests:
            self._gs.cancelFpsLimit(requests["fps"])

    @Slot(object, bool)
    def _profile_finished(self, request, succeeded):
        self._finish_request("profile", request, succeeded)

    @Slot(object, bool)
    def _fps_finished(self, request, succeeded):
        self._finish_request("fps", request, succeeded)

    @Slot(object)
    def _profile_requested(self, request):
        self._superseded("profile", request)

    @Slot(object)
    def _fps_requested(self, request):
        self._superseded("fps", request)

    def _superseded(self, channel, request):
        if self._pending_rule is not None:
            key, requests, remaining, _ = self._pending_rule
            if channel in requests and requests[channel] != request:
                # The remaining write can still apply while this rule is relevant.
                remaining.discard(channel)
                self._pending_rule = (key, requests, remaining, None) if remaining else None

    def _finish_request(self, channel, request, succeeded):
        if self._pending_rule is None:
            return
        key, requests, remaining, detail = self._pending_rule
        if requests.get(channel) != request or channel not in remaining:
            return
        remaining.discard(channel)
        self._pending_rule = (key, requests, remaining, detail if succeeded else None) if remaining else None
        if detail is not None:
            if not succeeded:
                self.notice.emit("failed", detail)
            elif not remaining:
                self._show_loaded(detail)

    def resumeWrites(self):
        super().resumeWrites()
        if self._check_deferred:
            self._check_deferred = False
            self._check()

    def _check(self):
        if self._writes_paused:
            self._check_deferred = True
            return
        cur = self._np.state
        if self._on:
            self._emulator(cur)
        if not cur.get("playing"):
            # Steam's own UI in front of a running game is not "no game": only when the process is gone does the idle rule apply
            if self._applied and not getattr(self._np, "running", False):
                self._applied = ""      # the next game that starts gets its rule again
                if self._on and IDLE in self._rules:
                    self._apply(IDLE, "idle")
                else:
                    self._cancel_pending_rule()
            return
        if not self._on or cur.get("key") == self._applied:
            return
        self._applied = cur.get("key", "")
        for key, label in ((self._game_key(cur), "game"), (self._system_key(cur), "system"), (BASE, "base")):
            if key in self._rules:
                self._apply(key, f"{cur.get('title') or cur.get('key')}" if label == "game" else label)
                return
        self._cancel_pending_rule()
