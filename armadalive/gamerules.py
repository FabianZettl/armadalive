"""Remembers a power profile and FPS limit for a game or a whole system and applies it when that game starts."""
import json, os, subprocess
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import emusettings

CONFIG = os.path.expanduser("~/.config/armadalive/game_rules.json")


class GameRules(QObject):
    changed = Signal()

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
        self._applied = ""
        nowplaying.changed.connect(self._check)

    @Property("QVariant", notify=changed)
    def state(self):
        cur = self._np.state
        return dict(enabled=self._on, rules=[dict(key=k, **v) for k, v in sorted(self._rules.items())],
                    gameKey=self._game_key(cur), systemKey=self._system_key(cur), resOk=cur.get("system") in emusettings.SPECS)

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

    @Slot(str)
    def toggle(self, scope):
        """Save the current profile and FPS limit for this game or system, or forget the rule if there is one."""
        cur = self._np.state
        key = self._game_key(cur) if scope == "game" else self._system_key(cur)
        if not key:
            return
        if key in self._rules:
            del self._rules[key]
        else:
            self._rules[key] = dict(profile=self._sys.stats.get("profile", ""), fps=self._gs.state.get("limit", 0))
        self._save()

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

    def _check(self):
        cur = self._np.state
        if self._on:
            self._emulator(cur)
        if not cur.get("playing"):
            self._applied = ""      # the next game that starts gets its rule again
            return
        if not self._on or cur.get("key") == self._applied:
            return
        self._applied = cur.get("key", "")
        rule = self._rules.get(self._game_key(cur)) or self._rules.get(self._system_key(cur))
        if not rule:
            return
        if rule.get("profile"):
            subprocess.Popen(["armada-power", "profile", rule["profile"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rule.get("fps"):
            self._gs.setFpsLimit(int(rule["fps"]))
