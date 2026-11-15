"""Remembers a power profile and FPS limit for a game, a whole system, every other game (the base rule) or for when no game runs
(the idle rule), and applies it when that game starts or the last game ends."""
import json, logging, os, subprocess
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import emusettings, persistence

CONFIG = os.path.expanduser("~/.config/armadalive/game_rules.json")
LOG = logging.getLogger(__name__)


IDLE, BASE = "default:idle", "default:base"   # rule keys that belong to no game


def validate_settings(saved):
    if not isinstance(saved, dict):
        raise ValueError("expected an object")
    if not isinstance(saved.get("enabled", True), bool):
        raise ValueError("enabled must be a boolean")
    base = saved.get("base", {})
    if not isinstance(base, dict) or not all(
            value is None or isinstance(value, str) and "\n" not in value and "\r" not in value
            for value in base.values()):
        raise ValueError("base must contain original emulator settings")
    rules = saved.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("rules must be an object")
    for key, rule in rules.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(rule, dict):
            raise ValueError(f"invalid rule {key!r}")
        for field in ("profile", "title"):
            if not isinstance(rule.get(field, ""), str):
                raise ValueError(f"{key}.{field} must be text")
        for field, maximum in (("fps", 2**31 - 1), ("res", emusettings.MAX)):
            value = rule.get(field, 0)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{key}.{field} must be an integer from 0 to {maximum}")
    return True


def _target(spec):
    path, section, key, _ = spec
    return os.path.realpath(path), section, key


def _read_undo(path):
    try:
        with open(path, encoding="utf-8") as stream:
            entries = json.load(stream)
    except FileNotFoundError:
        return {}
    undo = {}
    if not isinstance(entries, list):
        raise ValueError("invalid emulator recovery file")
    for entry in entries:
        if (not isinstance(entry, list) or len(entry) != 4 or not all(isinstance(value, str) for value in entry)
                or not os.path.isabs(entry[0]) or "\0" in entry[0] or "\n" in entry[3] or "\r" in entry[3]):
            raise ValueError("invalid emulator recovery entry")
        target = tuple(entry[:3])
        if target in undo:
            raise ValueError("duplicate emulator recovery entry")
        undo[target] = entry[3]
    return undo


class GameRules(QObject):
    changed = Signal()
    notice = Signal(str, str)   # saved | removed | loaded | resolutionNextLaunch

    def __init__(self, nowplaying, gamescope, system):
        super().__init__()
        self._np, self._gs, self._sys = nowplaying, gamescope, system
        saved = persistence.read_json(CONFIG, validate_settings, {})
        self._rules, self._on = saved.get("rules", {}), saved.get("enabled", True)
        self._legacy_base = saved.get("base", {})
        self._undo_path = os.path.join(os.path.dirname(CONFIG), "emulator_undo.json")
        self._undo = None
        self._undo_uncertain = False
        if self._prepare_undo():
            self._restore_emulators()
        self._applied, self._loaded = "", ""
        self._checked = False
        self._scopes = self._current_scopes(nowplaying.state)
        self._writes_paused = self._check_deferred = self._legacy_deferred = False
        self._launch_key = ""
        self._launch_hold = QTimer(self)
        self._launch_hold.setSingleShot(True)
        # Match NowPlaying's Steam startup window after leaving Steam's UI.
        self._launch_hold.setInterval(25000)
        self._launch_hold.timeout.connect(self._launch_unobserved)
        self.history = None      # set by the app: lets a rule show the name of its game, not only the key
        nowplaying.changed.connect(self._check)
        if (legacy_changed := getattr(nowplaying, "legacyRulesChanged", None)) is not None:
            legacy_changed.connect(self._legacy_rules_changed)
            self._watch_legacy_rules()

    @Property("QVariant", notify=changed)
    def state(self):
        game, system, resolution = self._current_scopes(self._np.state)
        return dict(enabled=self._on, rules=sorted((dict(v, key=k, **self._describe(k, v)) for k, v in self._rules.items()), key=lambda r: (r["kind"], r["name"].lower())),
                    gameKey=game, systemKey=system, resOk=resolution, idleKey=IDLE, baseKey=BASE,
                    loaded=self._loaded, writesPaused=self._writes_paused)

    def pauseWrites(self):
        self._writes_paused = True
        self.changed.emit()

    def writesPending(self):
        return False  # Configuration writes complete on the owner thread.

    def resumeWrites(self):
        self._writes_paused = False
        if self._legacy_deferred:
            self._legacy_deferred = False
            self._legacy_rules_changed()
        if self._check_deferred:
            self._check()
        self.changed.emit()

    def _current_scopes(self, state):
        return self._game_key(state), self._system_key(state), state.get("system") in emusettings.SPECS

    def _describe(self, key, rule):
        """What the rules list shows for a key: its kind and the name of the game or system, never only the Steam id."""
        if key in (IDLE, BASE):
            return dict(kind="idle" if key == IDLE else "base", name="")
        kind, _, rest = key.partition(":")
        if kind == "game":
            return dict(kind="game", name=rule.get("title") or (self.history.title_of(rest) if self.history else "") or rest)
        return dict(kind="system", name=rest)

    @staticmethod
    def _canonical_game_key(state):
        return f"game:{state['key']}" if state.get("key") else ""

    @staticmethod
    def _legacy_game_key(state):
        legacy = state.get("legacyKey")
        return f"game:{legacy}" if legacy and (state.get("key") or "").startswith("esde:") else ""

    def _game_key(self, state):
        canonical = self._canonical_game_key(state)
        legacy = self._legacy_game_key(state)
        return legacy if canonical not in self._rules and legacy in self._rules else canonical

    def _pending_legacy_rule(self, state):
        identity = state.get("key") or ""
        pending = state.get("legacyPending", state.get("metadataPending", False))
        if not pending or not identity.startswith("esde:") or self._game_key(state) in self._rules:
            return ""
        system, _, path = identity[5:].partition("/")
        stem = os.path.splitext(os.path.basename(path))[0]
        legacy = f"game:{system}/{stem}"
        return legacy if legacy in self._rules else ""

    def _migrate_game_rule(self, state):
        legacy = self._legacy_game_key(state)
        if legacy not in self._rules:
            return False
        return self._migrate_game_rules(((legacy, self._canonical_game_key(state)),))

    def _migrate_game_rules(self, aliases):
        previous = self._rules
        updated = dict(previous)
        for legacy, canonical in aliases:
            if legacy in updated and canonical and canonical not in updated:
                updated[canonical] = updated.pop(legacy)
        if updated == previous:
            return False
        self._rules = updated
        try:
            self._write_settings(self._legacy_base)
        except (OSError, ValueError) as error:
            self._rules = previous
            LOG.warning("Could not migrate game rules: %s", error)
            return False
        return True

    def _legacy_rule_ids(self):
        return [key[5:] for key in self._rules if key.startswith("game:") and not key.startswith("game:esde:")]

    def _watch_legacy_rules(self):
        if (watch := getattr(self._np, "watch_legacy_rules", None)) is not None:
            watch(self._legacy_rule_ids())

    @Slot()
    def _legacy_rules_changed(self):
        if self._writes_paused:
            self._legacy_deferred = True
            return
        aliases = []
        for key in self._legacy_rule_ids():
            canonical = self._np.legacy_rule_identity(key)
            if canonical:
                aliases.append((f"game:{key}", f"game:{canonical}"))
        if aliases and self._migrate_game_rules(aliases):
            self.changed.emit()
        self._check()

    @staticmethod
    def _system_key(state):
        return f"system:{state['system']}" if state.get("system") and state.get("kind") == "game" else ""

    def _save(self):
        self._write_settings(self._legacy_base)
        self._watch_legacy_rules()
        self.changed.emit()

    def _write_settings(self, legacy):
        saved = {"enabled": self._on, "rules": self._rules}
        if legacy:
            saved["base"] = legacy
        persistence.write_json(CONFIG, saved, indent=1, follow_symlinks=True)

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
            if scope == "game" and key == self._canonical_game_key(cur):
                self._rules.pop(self._legacy_game_key(cur), None)
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
            self._save()
            self.notice.emit("removed", self._label(key, self._np.state))

    @Slot(bool)
    def setEnabled(self, on):
        if self._writes_paused:
            return
        self._on = bool(on)
        self._save()
        if not self._on and self._prepare_undo():
            self._restore_emulators()

    def _write_undo(self, undo):
        # An exception can occur after replacing or unlinking the visible file.
        self._undo_uncertain = True
        if undo:
            persistence.write_json(self._undo_path, [[*key, value] for key, value in undo.items()])
        else:
            persistence.remove(self._undo_path)
        self._undo = undo
        self._undo_uncertain = False

    def _prepare_undo(self):
        try:
            if self._undo is None:
                self._undo = _read_undo(self._undo_path)
            if self._undo_uncertain:
                self._write_undo(self._undo)
            if self._legacy_base:
                legacy = {}
                for system, original in self._legacy_base.items():
                    if original is None or system not in emusettings.SPECS:
                        continue
                    target = _target(emusettings.SPECS[system])
                    if target in self._undo:
                        continue
                    if target in legacy and legacy[target] != original:
                        raise ValueError(f"{target[0]}: conflicting legacy originals")
                    legacy[target] = original
                if legacy:
                    self._write_undo({**self._undo, **legacy})
                self._write_settings({})
                self._legacy_base = {}
        except (OSError, ValueError, RecursionError) as error:
            LOG.warning("Could not prepare emulator recovery: %s", error)
            return False
        return True

    def _restore_emulators(self, keep=None):
        if not self._undo:
            return
        supported = {_target(spec) for spec in emusettings.SPECS.values()}
        remaining = dict(self._undo)
        for target, original in self._undo.items():
            if target == keep:
                continue
            try:
                if target not in supported or not emusettings.update_setting((*target, "{}"), lambda _: original):
                    raise OSError(f"{target[0]} is unavailable")
                # Retrying after a failed directory sync may find the original
                # already visible. Sync its location before discarding the undo.
                persistence._sync_directory(os.path.dirname(target[0]))
                del remaining[target]
            except (OSError, ValueError) as error:
                LOG.warning("Could not restore emulator resolution: %s", error)
        if remaining != self._undo:
            try:
                self._write_undo(remaining)
            except OSError as error:
                LOG.warning("Could not clear emulator recovery: %s", error)

    def _resolution(self, cur):
        rule = self._rules.get(self._game_key(cur)) or self._rules.get(self._system_key(cur)) or {}
        return rule.get("res")

    def prepare_esde_launch(self, system, path, title):
        """Return None for pending identity, an empty string when ready or an error."""
        if system not in emusettings.SPECS:
            return ""
        if self._writes_paused:
            return "Game rules are paused during backup"
        launch_state = getattr(self._np, "esde_launch_state", None)
        if launch_state is None:
            return ""
        cur = launch_state(system, path, title)
        if self._on and (pending := self._pending_legacy_rule(cur)):
            if self._rules[pending].get("res") or self._rules.get(self._system_key(cur), {}).get("res"):
                return None
        problem = self._emulator(cur)
        if not problem and cur.get("key"):
            self._launch_key = cur["key"]
            self._launch_hold.start()
        return problem

    @Slot()
    def _launch_unobserved(self):
        self._launch_key = ""
        self._launch_hold.stop()
        self._check()

    def _emulator(self, cur):
        """Apply a selected game's resolution and restore overrides when leaving it."""
        spec = emusettings.SPECS.get(cur.get("system")) if cur.get("kind") == "game" else None
        if (self._on and cur.get("system") == "steam" and not cur.get("playing")
                and getattr(self._np, "running", False)):
            return ""  # Steam's overlay can hide the game without ending it.
        if not self._prepare_undo():
            return "Could not prepare emulator resolution recovery"
        resolution = self._resolution(cur) if self._on and spec and not self._pending_legacy_rule(cur) else None
        target = _target(spec) if spec else None
        playing = cur.get("playing")
        self._restore_emulators(keep=target if playing or resolution else None)
        if playing:
            return ""
        if not resolution:
            return "Could not restore emulator resolution" if target in self._undo else ""
        value = spec[3].format(resolution)

        def remember(original):
            if original is None:
                raise ValueError("the emulator resolution option is missing")
            if original == value:
                return original
            # Restoring another emulator above can make the journal uncertain.
            if self._undo_uncertain or target not in self._undo:
                self._write_undo({target: original, **self._undo})
            return value

        try:
            if emusettings.update_setting((*target, spec[3]), remember):
                return ""
            LOG.warning("Could not apply emulator resolution: %s is unavailable", target[0])
        except (OSError, ValueError) as error:
            LOG.warning("Could not apply emulator resolution: %s", error)
        return "Could not apply emulator resolution"

    def _apply(self, rule, label):
        if rule.get("profile"):
            subprocess.Popen(["armada-power", "profile", rule["profile"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rule.get("fps"):
            self._gs.setFpsLimit(int(rule["fps"]))
        self._loaded = f"{label} · {self._summary(rule)}"
        self.changed.emit()
        self.notice.emit("loaded", self._loaded)

    def _check(self):
        if self._writes_paused:
            self._check_deferred = True
            return
        self._check_deferred = False
        cur = self._np.state
        migrated = self._migrate_game_rule(cur)
        scopes = self._current_scopes(cur)
        if migrated or self._scopes != scopes:
            self._scopes = scopes
            self.changed.emit()
        if self._launch_key and cur.get("key") == self._launch_key and cur.get("playing"):
            self._launch_key = ""
            self._launch_hold.stop()
        if not self._launch_key:
            self._emulator(cur)
        if not cur.get("playing"):
            # Steam's own UI in front of a running game is not "no game": only when the process is gone does the idle rule apply
            if self._applied and not getattr(self._np, "running", False):
                self._applied = ""      # the next game that starts gets its rule again
                if self._on and IDLE in self._rules:
                    self._apply(self._rules[IDLE], "idle")
            return
        game = cur.get("key") or ""
        if not self._on or not game:
            return
        if game != self._applied:
            self._applied = game
            self._checked = False
        if self._checked or self._pending_legacy_rule(cur):
            return
        self._checked = True
        system = cur.get("system")
        if not self._launch_key and system in emusettings.SPECS and (resolution := self._resolution(cur)):
            if emusettings.read(system) != emusettings.SPECS[system][3].format(resolution):
                self.notice.emit("resolutionNextLaunch", cur.get("title") or game)
        for key, label in ((self._game_key(cur), "game"), (self._system_key(cur), "system"), (BASE, "base")):
            if key in self._rules:
                self._apply(self._rules[key], f"{cur.get('title') or cur.get('key')}" if label == "game" else label)
                return
