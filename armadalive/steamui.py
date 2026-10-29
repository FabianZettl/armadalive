"""The app highlighted in Steam's Big Picture UI, read from Steam's own browser through its local debug port.

Steam only opens that port while ~/.steam/steam/.cef-enable-remote-debugging exists (Decky Loader creates it). Read-only:
the script only looks at which element has the gamepad focus and which app that element belongs to.
"""
import json, urllib.request
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

LIST_URL = "http://127.0.0.1:8080/json"
FOCUS_JS = """(() => {
  const leaf = document.querySelector("[class~=gpfocus]");
  if (!leaf) return "{}";
  const key = Object.keys(leaf).find(k => k.startsWith("__reactFiber$"));
  let f = key && leaf[key];
  for (let d = 0; f && d < 40; d++, f = f.return) {
    const a = (f.memoizedProps || {}).app;
    if (a && typeof a.appid === "number") return JSON.stringify({ appid: a.appid, name: a.display_name || "" });
  }
  return "{}";
})()"""


def _target():
    """The Big Picture window, whatever language Steam runs in ("Big-Picture-Modus", "Big Picture Mode", ...)."""
    try:
        for t in json.load(urllib.request.urlopen(LIST_URL, timeout=0.6)):
            title = t.get("title", "").lower()
            if t.get("type") == "page" and title.startswith("big") and "picture" in title:
                return t.get("webSocketDebuggerUrl")
    except (OSError, ValueError):
        pass
    return None


class SteamUi(QObject):
    selected = Signal(object, str)  # appid (a Python int: shortcut ids exceed 32 bit) and name, (0, "") when nothing is highlighted

    def __init__(self):
        super().__init__()
        self._last, self._busy, self._ticks = (0, ""), 0, 0
        self._ws = QWebSocket()
        self._ws.textMessageReceived.connect(self._reply)
        self._ws.disconnected.connect(lambda: self._set((0, "")))
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(700)

    @property
    def connected(self):
        return self._ws.state() == QAbstractSocket.SocketState.ConnectedState

    def _set(self, value):
        if value != self._last:
            self._last = value
            self.selected.emit(*value)

    def _tick(self):
        self._ticks += 1
        state = self._ws.state()
        if state == QAbstractSocket.SocketState.ConnectedState:
            self._busy = max(0, self._busy - 1)
            if not self._busy:
                self._busy = 4  # a lost answer must not stall polling for good
                self._ws.sendTextMessage(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                                     "params": {"expression": FOCUS_JS, "returnByValue": True}}))
        elif state == QAbstractSocket.SocketState.UnconnectedState and self._ticks % 4 == 0:
            url = _target()  # Steam may be starting or restarting: look again every few seconds
            if url:
                self._ws.open(QUrl(url))

    def _reply(self, text):
        self._busy = 0
        try:
            app = json.loads(json.loads(text)["result"]["result"]["value"])
        except (ValueError, KeyError, TypeError):
            return
        # an empty answer (a game's details page, a menu) keeps the last highlighted app: the screen must not fall back
        # to the app grid while the user opens a game or it starts; only closing Big Picture clears the selection
        if app.get("appid"):
            self._set((app["appid"], app.get("name", "")))
