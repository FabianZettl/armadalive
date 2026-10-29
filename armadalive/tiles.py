"""The order of the dashboard tiles, remembered between runs."""
import json, os
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtQml import QJSValue

CONFIG = os.path.expanduser("~/.config/armadalive/tiles.json")


def _ids(value):
    """A list from QML arrives as a QJSValue, a list from Python (tests) as it is."""
    if isinstance(value, QJSValue):
        value = value.toVariant()
    return [i for i in list(value or []) if isinstance(i, str)]


class Tiles(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        try:
            with open(CONFIG) as f:
                saved = json.load(f).get("order", [])
            self._order = [i for i in saved if isinstance(i, str)] if isinstance(saved, list) else []
        except (OSError, ValueError, AttributeError):
            self._order = []

    @Property("QVariant", notify=changed)
    def order(self):
        return self._order

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"order": self._order}, f)
        self.changed.emit()

    @Slot("QVariant", result="QVariant")
    def arrange(self, ids):
        """The tile ids in the saved order; tiles that are new (or were never moved) keep their place at the end."""
        ids = _ids(ids)
        known = [i for i in self._order if i in ids]
        return known + [i for i in ids if i not in known]

    @Slot(str, str, "QVariant")
    def swap(self, a, b, ids):
        """Swap two tiles; `ids` is the order on screen right now."""
        ids = self.arrange(ids)
        if a in ids and b in ids and a != b:
            i, j = ids.index(a), ids.index(b)
            ids[i], ids[j] = ids[j], ids[i]
            self._order = ids
            self._save()

    @Slot()
    def reset(self):
        self._order = []
        self._save()
