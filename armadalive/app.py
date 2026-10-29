import json, os, signal, sys
from PySide6.QtCore import QPoint, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from . import __version__
from .admin import Admin
from .apps import Apps
from .ayn import AynButton
from .backup import Backup
from .battery import Battery
from .closer import Closer
from .gamepad import Pad
from .media import Media
from .palette import Palette
from .gamerules import GameRules
from .controls import Controls
from .gamescope import Gamescope
from .health import Health
from .nowplaying import NowPlaying
from .settings import Settings
from .shell import Shell
from .steamui import SteamUi
from .tiles import Tiles
from .ui import UiSettings
from .updater import Updater
from .system import SystemMonitor

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("ArmadaLive")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("armadalive")
    engine = QQmlApplicationEngine()
    # the context does not own these objects: keep them referenced for the life of the app
    gamescope, steamui = Gamescope(), SteamUi()
    now, monitor = NowPlaying(gamescope, steamui), SystemMonitor(fps=lambda: gamescope.state["fps"])
    backends = dict(steamui=steamui, gamescope=gamescope, nowPlaying=now, system=monitor, ayn=AynButton(), settings=Settings(), apps=Apps(), shell=Shell(), controls=Controls(), ui=UiSettings(), updater=Updater(), admin=Admin(),
                    health=Health(steamui), rules=GameRules(now, gamescope, monitor), tileStore=Tiles(),
                    battery=Battery(), media=Media(), backup=Backup(), artwork=Palette())
    pad = backends["pad"] = Pad()   # must stay referenced, like the rest
    backends["closer"] = Closer(pad, gamescope, now, backends["ui"])
    for name, obj in backends.items():
        engine.rootContext().setContextProperty(name, obj)
    # closing the window only hides it: the app keeps listening for the AYN button and can bring itself back
    app.setQuitOnLastWindowClosed(False)
    # SIGUSR1 does what the AYN button does (used by the app-drawer launcher)
    signal.signal(signal.SIGUSR1, lambda *_: backends["ayn"].pressed.emit())
    wake = QTimer()
    wake.timeout.connect(lambda: None)  # keeps the interpreter running so it notices the signal
    wake.start(250)
    engine.load(QUrl.fromLocalFile(HERE + "/qml/Main.qml"))
    if not engine.rootObjects():
        return 1
    if "--snapshot" in sys.argv:  # render the first frames to a PNG and exit, for docs and tests
        out = sys.argv[sys.argv.index("--snapshot") + 1]
        page = int(sys.argv[sys.argv.index("--page") + 1]) if "--page" in sys.argv else 0
        window = engine.rootObjects()[0]
        # a snapshot always shows a fixed game state, otherwise whatever ES-DE or Steam is doing at that moment throws the page
        # back to "Game": {"event": {...}} like ES-DE sends, or {"ui": [appid, "name"]} for Steam's UI; none means idle
        demo = json.loads(sys.argv[sys.argv.index("--demo") + 1]) if "--demo" in sys.argv else {}
        backends["nowPlaying"].pin(demo.get("event"), demo.get("ui"))
        window.setProperty("page", ["now", "apps", "mode", "system", "prefs", "tuning", "cheats", "manual", "graphs"][page] if page < 9 else "now")
        if "--theme" in sys.argv:  # for screenshots too: not written to the settings file
            backends["ui"]._s["theme"], backends["ui"]._s["accent"] = sys.argv[sys.argv.index("--theme") + 1], ""
            backends["ui"].changed.emit()
        if "--lang" in sys.argv:  # for screenshots: not written to the settings file
            backends["ui"]._s["lang"] = sys.argv[sys.argv.index("--lang") + 1]
            backends["ui"].changed.emit()
        if "--click" in sys.argv:  # x,y,ms: tap the window ms milliseconds in, to test touch behaviour
            x, y, ms = (int(v) for v in sys.argv[sys.argv.index("--click") + 1].split(","))
            QTimer.singleShot(ms, lambda x=x, y=y: QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y)))
        if "--hold" in sys.argv:  # x,y,ms: press and hold at that point from ms on for 1.2 s, to test long presses
            x, y, ms = (int(v) for v in sys.argv[sys.argv.index("--hold") + 1].split(","))
            QTimer.singleShot(ms, lambda x=x, y=y: QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y)))
            QTimer.singleShot(ms + 1200, lambda x=x, y=y: QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y)))
        for i, flag in enumerate(sys.argv):  # --ayn short:ms or long:ms: press the AYN button that many milliseconds in
            if flag == "--ayn":
                kind, ms = sys.argv[i + 1].split(":")
                ayn = backends["ayn"]
                QTimer.singleShot(int(ms), lambda ayn=ayn, kind=kind: (ayn.pressed.emit(), kind == "long" and ayn.longPressed.emit()))
        if "--demo-later" in sys.argv:  # ms:json, switch to another pinned game that many milliseconds in
            ms, later = sys.argv[sys.argv.index("--demo-later") + 1].split(":", 1)
            QTimer.singleShot(int(ms), lambda: backends["nowPlaying"].pin(json.loads(later).get("event"), json.loads(later).get("ui")))
        if "--close-demo" in sys.argv:  # ms: hold Start + Select that many milliseconds in, with a pretend game in front
            closer = backends["closer"]
            closer.target = lambda: ([], "Demo Game")
            from .gamepad import BTN_SELECT, BTN_START, EVENT
            press = b"".join(EVENT.pack(0, 0, 1, code, 1) for code in (BTN_SELECT, BTN_START))
            QTimer.singleShot(int(sys.argv[sys.argv.index("--close-demo") + 1]), lambda: backends["pad"].feed("demo", press))
        delay = int(sys.argv[sys.argv.index("--delay") + 1]) if "--delay" in sys.argv else 3000
        QTimer.singleShot(delay, lambda: (print("dimmed:", window.property("dimmed")), QQuickWindow.grabWindow(window).save(out), app.quit()))
    return app.exec()
