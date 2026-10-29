import json, os, signal, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from . import __version__
from .admin import Admin
from .apps import Apps
from .ayn import AynButton
from .controls import Controls
from .gamescope import Gamescope
from .nowplaying import NowPlaying
from .settings import Settings
from .shell import Shell
from .steamui import SteamUi
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
    backends = dict(steamui=steamui, gamescope=gamescope, nowPlaying=NowPlaying(gamescope, steamui), system=SystemMonitor(), ayn=AynButton(), settings=Settings(), apps=Apps(), shell=Shell(), controls=Controls(), ui=UiSettings(), updater=Updater(), admin=Admin())
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
        if "--demo" in sys.argv:  # pin a game state: {"event": {...}} like ES-DE sends, or {"ui": [appid, "name"]} for Steam's UI
            demo = json.loads(sys.argv[sys.argv.index("--demo") + 1])
            backends["nowPlaying"].pin(demo.get("event"), demo.get("ui"))
        window.setProperty("page", ["now", "apps", "mode", "system", "prefs", "tuning", "cheats", "manual"][page] if page < 8 else "now")
        if "--lang" in sys.argv:  # for screenshots: not written to the settings file
            backends["ui"]._s["lang"] = sys.argv[sys.argv.index("--lang") + 1]
            backends["ui"].changed.emit()
        QTimer.singleShot(3000, lambda: (QQuickWindow.grabWindow(window).save(out), app.quit()))
    return app.exec()
