"""The app highlighted in Steam's Big Picture UI, read from Steam's own browser through its local debug port.

Steam only opens that port while remote debugging is on: the file ~/.steam/steam/.cef-enable-remote-debugging (Decky Loader creates it) or
the switch in Steam's developer settings. Read-only:
the script only looks at which element has the gamepad focus and which app that element belongs to.
"""
import json
from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

LIST_URL = "http://127.0.0.1:8080/json"
FOCUS_JS = """(() => {
  const leaf = document.querySelector("[class~=gpfocus]");
  if (!leaf) return "{}";
  const key = Object.keys(leaf).find(k => k.startsWith("__reactFiber$"));
  let f = key && leaf[key];
  for (let d = 0; f && d < 40; d++, f = f.return) {
    const g = (f.memoizedProps || {}).game;   // a tile of the Ludo plugin (RomM)
    if (g && typeof g.rom_id === "number") return JSON.stringify({ appid: "ludo:" + g.rom_id, name: g.name || "", screenshot: g.screenshot || "" });
    const a = (f.memoizedProps || {}).app;
    if (a && typeof a.appid === "number") return JSON.stringify({ appid: a.appid, name: a.display_name || "" });
  }
  return "{}";
})()"""


def _target(pages, shared=False):
    """Select the Big Picture window or SharedJSContext from Steam's page list."""
    for page in pages:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title", "")).lower()
        if page.get("type") == "page" and (title == "sharedjscontext" if shared else "big" in title and "picture" in title):
            url = page.get("webSocketDebuggerUrl")
            if isinstance(url, str) and url:
                return url
    return None


class _Discovery(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._network.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._waiters = []

    def request(self, shared, done):
        self._waiters.append((shared, done))
        if len(self._waiters) > 1:
            return
        request = QNetworkRequest(QUrl(LIST_URL))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self._network.get(request)
        limit = 256 * 1024
        reply.setReadBufferSize(limit + 1)
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.timeout.connect(reply.abort)
        timer.start(600)

        def limit_size():
            if reply.bytesAvailable() > limit:
                reply.abort()

        def finish():
            pages = []
            if reply.error() == QNetworkReply.NetworkError.NoError and reply.bytesAvailable() <= limit:
                try:
                    value = json.loads(bytes(reply.readAll()))
                    if isinstance(value, list):
                        pages = value
                except (ValueError, UnicodeError):
                    pass
            timer.stop()
            reply.deleteLater()
            waiting, self._waiters = self._waiters, []
            for use_shared, callback in waiting:
                callback(_target(pages, use_shared))

        reply.readyRead.connect(limit_size)
        reply.finished.connect(finish)


_discovery = None


def _discover(shared, done):
    global _discovery
    if _discovery is None:
        _discovery = _Discovery(QCoreApplication.instance())
    _discovery.request(shared, done)


_live = set()
MAX_EVALS = 8


def eval_js(expression, done, timeout=30000, *, valid=None):
    """Run a Steam script while valid; done(value) gets its awaited result or None."""
    if len(_live) >= MAX_EVALS:
        QTimer.singleShot(0, lambda: done(None))
        return
    ws = QWebSocket()
    timer = QTimer(ws)
    timer.setSingleShot(True)

    def finish(value):
        if ws not in _live:
            return
        _live.discard(ws)
        timer.stop()
        ws.abort()
        ws.deleteLater()
        done(value)

    def discovered(url):
        if ws not in _live:
            return
        if url:
            ws.open(QUrl(url))
        else:
            finish(None)

    def reply(text):
        try:
            answer = json.loads(text)
            if answer.get("id") == 7:
                result = answer.get("result", {})
                finish(None if "exceptionDetails" in result else result.get("result", {}).get("value"))
        except (ValueError, AttributeError):
            return

    def send():
        if ws not in _live:
            return
        if valid is not None and not valid():
            finish(None)
            return
        ws.sendTextMessage(json.dumps(
            {"id": 7, "method": "Runtime.evaluate", "params": {"expression": expression, "awaitPromise": True, "returnByValue": True}}))

    ws.connected.connect(send)
    ws.textMessageReceived.connect(reply)
    ws.errorOccurred.connect(lambda *_: finish(None))
    ws.disconnected.connect(lambda: finish(None))
    _live.add(ws)
    timer.timeout.connect(lambda: finish(None))
    timer.start(timeout)
    _discover(True, discovered)


class SteamUi(QObject):
    selected = Signal(object, str)  # appid (a Python int: shortcut ids exceed 32 bit; "ludo:<rom id>" for a Ludo tile) and name, (0, "") when nothing is highlighted

    def __init__(self):
        super().__init__()
        self._last, self._busy, self._ticks = (0, ""), 0, 0
        self._discovering = False
        self._request_id = 0
        self.screenshot = ""   # server path of the highlighted Ludo game's screenshot
        self._ws = QWebSocket()
        self._ws.textMessageReceived.connect(self._reply)
        self._ws.disconnected.connect(self._disconnected)
        self._connect_timeout = QTimer(self)
        self._connect_timeout.setSingleShot(True)
        self._connect_timeout.timeout.connect(self._ws.abort)
        self._ws.connected.connect(self._connect_timeout.stop)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(700)

    @property
    def connected(self):
        return self._ws.state() == QAbstractSocket.SocketState.ConnectedState

    def _disconnected(self):
        self._connect_timeout.stop()
        self._busy = 0
        self.screenshot = ""
        self._set((0, ""))

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
                self._request_id += 1
                self._ws.sendTextMessage(json.dumps({"id": self._request_id, "method": "Runtime.evaluate",
                                                     "params": {"expression": FOCUS_JS, "returnByValue": True}}))
        elif (state == QAbstractSocket.SocketState.UnconnectedState and self._ticks % 4 == 0
              and not self._discovering):
            self._discovering = True
            _discover(False, self._connect)

    def _connect(self, url):
        self._discovering = False
        if url and self._ws.state() == QAbstractSocket.SocketState.UnconnectedState:
            self._connect_timeout.start(2000)
            self._ws.open(QUrl(url))

    def _reply(self, text):
        try:
            reply = json.loads(text)
            if reply.get("id") != self._request_id:
                return
            self._busy = 0
            app = json.loads(reply["result"]["result"]["value"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return
        if not isinstance(app, dict):
            return
        # an empty answer (a game's details page, a menu) keeps the last highlighted app: the screen must not fall back
        # to the app grid while the user opens a game or it starts; only closing Big Picture clears the selection
        appid, name, screenshot = app.get("appid"), app.get("name", ""), app.get("screenshot", "")
        if (type(appid) is int and appid > 0 or isinstance(appid, str) and appid.startswith("ludo:")
                and appid[5:].isdigit()) and isinstance(name, str) and isinstance(screenshot, str):
            self.screenshot = screenshot   # before _set: its signal reads this
            self._set((appid, name))
