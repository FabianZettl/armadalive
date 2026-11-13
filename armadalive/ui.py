"""Look of the app: theme and accent, remembered between runs."""
import json, os
from PySide6.QtCore import Property, QObject, Signal, Slot

CONFIG = os.path.expanduser("~/.config/armadalive/ui.json")


DEFAULTS = dict(theme="stock", accent="", lang="en", animate=True, dim=True, close=True, heat=85, apps=True, ledFollow=True, onboarded=True)


class UiSettings(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        try:
            with open(CONFIG) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        # saved values win over the defaults; keys we do not know are dropped
        self._s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}} if isinstance(saved, dict) else dict(DEFAULTS)
        if not saved:      # a fresh install (no settings yet) gets the first-run setup; an install that already has settings does not
            self._s["onboarded"] = False

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump(self._s, f)
        self.changed.emit()

    @Slot(str)
    def setTheme(self, key):
        self._s["theme"] = key
        self._s["accent"] = ""  # a new theme starts with its own accent
        self._save()

    @Slot(str)
    def applyFont(self, family):
        """The app's font for every text that sets no family of its own (the theme's `font`); an empty name goes back to the system's."""
        import glob
        from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
        if QGuiApplication.instance() is None:
            return
        if not hasattr(self, "_fonts"):    # the fonts that ship with the app (armadalive/fonts)
            self._fonts = [QFontDatabase.addApplicationFont(f) for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "*.ttf")))]
        if not hasattr(self, "_base_font"):
            self._base_font = QGuiApplication.font()
        font = QFont(self._base_font)
        if family:
            font.setFamily(family)
        QGuiApplication.setFont(font)

    @Slot(bool)
    def setOnboarded(self, done):
        """Whether the first-run setup has been gone through (false shows it again)."""
        self._s["onboarded"] = bool(done)
        self._save()

    @Slot(bool)
    def setLedFollow(self, on):
        """The stick LEDs take the theme's accent colour (until the user picks a colour of their own)."""
        self._s["ledFollow"] = bool(on)
        self._save()

    @Slot(bool)
    def setDim(self, on):
        self._s["dim"] = bool(on)
        self._save()

    @Slot(bool)
    def setApps(self, on):
        self._s["apps"] = bool(on)
        self._save()

    @Slot(int)
    def setHeat(self, degrees):
        if degrees in (0, 80, 85, 90):    # 0 = no warning
            self._s["heat"] = degrees
            self._save()

    @Slot(bool)
    def setClose(self, on):
        self._s["close"] = bool(on)
        self._save()

    @Slot(bool)
    def setAnimate(self, on):
        self._s["animate"] = bool(on)
        self._save()

    @Slot(str)
    def setLang(self, lang):
        if lang in ("en", "de"):
            self._s["lang"] = lang
            self._save()

    @Slot(str)
    def setAccent(self, rgb):
        self._s["accent"] = rgb if len(rgb) == 6 else ""
        self._save()
