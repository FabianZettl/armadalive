"""Remembers a power profile and FPS limit for a game, a whole system, every other game (the base rule) or for when no game runs
(the idle rule), and applies it when that game starts or the last game ends."""
import json, os, subprocess
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import emusettings

CONFIG = os.path.expanduser("~/.config/armadalive/game_rules.json")


IDLE, BASE = "default:idle", "default:base"   # rule keys that belong to no game


class GameRules(QObject):
    changed = Signal()
    notice = Signal(str, str)   # saved | removed | loaded, and what it was about

    def __init__(self, nowplaying, gamescope, system):
        super().__init__()
        self._np, self._gs, self._sys = nowplaying, gamescope, system
        try:
            with open(CONFIG) as f:
                saved = json.load(f)
            self._rules, self._on = dict(saved.get("rules", {})), bool(saved.get("enabled", True))
            self._base = dict(saved.get("base", {}))
        except (OSError, ValueError, AttributeError):
            self._rules, self._on, self._base = {}, True, {}
        self._applied, self._loaded = "", ""
        nowplaying.changed.connect(self._check)

    @Property("QVariant", notify=changed)
    def state(self):
        cur = self._np.state
        return dict(enabled=self._on, rules=[dict(key=k, **v) for k, v in sorted(self._rules.items())],
                    gameKey=self._game_key(cur), systemKey=self._system_key(cur), resOk=cur.get("system") in emusettings.SPECS,
                    idleKey=IDLE, baseKey=BASE, loaded=self._loaded)

    @staticmethod
    def _game_key(state):
        return f"game:{state['key']}" if state.get("key") else ""

    @staticmethod
    def _system_key(state):
        return f"system:{state['system']}" if state.get("system") and state.get("kind") == "game" else ""

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"enabled": self._on, "rules": self._rules, "base": self._base}, f, indent=1)
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
        cur = self._np.state
        key = {"game": self._game_key(cur), "system": self._system_key(cur), "idle": IDLE, "base": BASE}.get(scope, "")
        if not key:
            return
        if key in self._rules:
            del self._rules[key]
            code = "removed"
        else:
            self._rules[key] = dict(profile=self._sys.stats.get("profile", ""), fps=self._gs.state.get("limit", 0))
            code = "saved"
        self._save()
        self.notice.emit(code, self._label(key, cur) + (f" · {self._summary(self._rules[key])}" if code == "saved" else ""))

    @staticmethod
    def _summary(rule):
        return (rule.get("profile") or "–") + (f", {rule['fps']} FPS" if rule.get("fps") else "")

    @Slot()
    def cycleRes(self):
        """Step this game's render resolution through off, 1x ... 5x; a game without a rule gets one that only holds the resolution."""
        key = self._game_key(self._np.state)
        if not key or self._np.state.get("system") not in emusettings.SPECS:
            return
        rule = self._rules.setdefault(key, dict(profile="", fps=0))
        rule["res"] = (rule.get("res", 0) + 1) % (emusettings.MAX + 1)
        self._save()

    @Slot(str)
    def remove(self, key):
        if self._rules.pop(key, None) is not None:
            self._save()
            self.notice.emit("removed", self._label(key, self._np.state))

    @Slot(bool)
    def setEnabled(self, on):
        self._on = bool(on)
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

    def _apply(self, rule, label):
        if rule.get("profile"):
            subprocess.Popen(["armada-power", "profile", rule["profile"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rule.get("fps"):
            self._gs.setFpsLimit(int(rule["fps"]))
        self._loaded = f"{label} · {self._summary(rule)}"
        self.changed.emit()
        self.notice.emit("loaded", self._loaded)

    def _check(self):
        cur = self._np.state
        if self._on:
            self._emulator(cur)
        if not cur.get("playing"):
            # Steam's own UI in front of a running game is not "no game": only when the process is gone does the idle rule apply
            if self._applied and not getattr(self._np, "running", False):
                self._applied = ""      # the next game that starts gets its rule again
                if self._on and IDLE in self._rules:
                    self._apply(self._rules[IDLE], "idle")
            return
        if not self._on or cur.get("key") == self._applied:
            return
        self._applied = cur.get("key", "")
        for key, label in ((self._game_key(cur), "game"), (self._system_key(cur), "system"), (BASE, "base")):
            if key in self._rules:
                self._apply(self._rules[key], f"{cur.get('title') or cur.get('key')}" if label == "game" else label)
                return
