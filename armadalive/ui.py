"""Look of the app: theme and accent, remembered between runs."""
import json, os
from PySide6.QtCore import Property, QObject, Signal, Slot

CONFIG = os.path.expanduser("~/.config/armadalive/ui.json")


class UiSettings(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        try:
            self._s = dict(theme="stock", accent="", lang="en", animate=True, **json.load(open(CONFIG)))
        except (OSError, ValueError, TypeError):
            self._s = dict(theme="stock", accent="", lang="en", animate=True)

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        json.dump(self._s, open(CONFIG, "w"))
        self.changed.emit()

    @Slot(str)
    def setTheme(self, key):
        self._s["theme"] = key
        self._s["accent"] = ""  # a new theme starts with its own accent
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
