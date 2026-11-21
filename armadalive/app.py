import json, os, signal, sys
from PySide6.QtCore import QObject, QPoint, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
import shiboken6

from . import __version__
from .admin import Admin
from .apps import Apps
from .artwork import VectorArtwork
from .gameinfo import GameInfo
from .history import History
from . import steamlib
from .ayn import AynButton
from .backup import Backup
from .battery import Battery
from .closer import Closer
from .gamepad import Pad
from .ludo import LudoSync
from .manuals import Manuals
from .media import Media
from .palette import Palette
from .gamerules import GameRules
from .controls import Controls
from .gamescope import Gamescope
from .health import Health
from .nowplaying import NowPlaying
from .settings import CONFIRM_S, Settings
from .shell import Shell
from .steamshortcuts import SteamShortcuts
from .steamui import SteamUi
from .activity import Activity
from .tasks import Tasks
from .thermal import Thermal
from .tiles import Tiles
from .trackpad import Trackpad
from .ui import UiSettings, saved_scale
from .updater import Updater
from .onboarding import Onboarding
from .system import SystemMonitor
from .cheats import Cheats
from .controls_layout import ControlsLayout
from .emulator_control import EmulatorControl

HERE = os.path.dirname(os.path.abspath(__file__))


def install_signal_handlers(app, ayn):
    def request_exit(signum, _frame):
        # A nonzero exit lets the launcher retry when the Plasma session appears.
        QTimer.singleShot(0, lambda: app.exit(128 + signum))

    signal.signal(signal.SIGTERM, request_exit)
    signal.signal(signal.SIGINT, request_exit)
    signal.signal(signal.SIGUSR1, lambda *_: ayn.pressed.emit())
    signal.signal(signal.SIGUSR2, lambda *_: (ayn.pressed.emit(), ayn.released.emit()))
    wake = QTimer(app)
    wake.timeout.connect(lambda: None)  # Let Python handle signals while Qt is idle.
    wake.start(250)


def main():
    os.environ.setdefault("QT_SCALE_FACTOR", str(saved_scale() / 100))   # a QT_SCALE_FACTOR from the service file wins
    app = QGuiApplication(sys.argv)
    app.setApplicationName("ArmadaLive")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("armadalive")
    engine = QQmlApplicationEngine()
    engine.addImageProvider("vectors", VectorArtwork())
    # the context does not own these objects: keep them referenced for the life of the app
    gamescope, steamui = Gamescope(), SteamUi()
    now, monitor = NowPlaying(gamescope, steamui), SystemMonitor(fps=lambda: gamescope.state["fps"])
    layout = ControlsLayout()
    emulator_ctrl = EmulatorControl()
    history = History(now, steam_titles=lambda: {g["id"]: g["name"] for g in steamlib.games(art=False)})
    now.history = history
    shortcuts = SteamShortcuts(now)
    app_catalog = Apps(history, shortcuts)
    backup = Backup((app_catalog, history))
    app.aboutToQuit.connect(backup.flushWriters)
    backends = dict(steamui=steamui, gamescope=gamescope, nowPlaying=now, system=monitor, ayn=AynButton(), settings=Settings(), apps=app_catalog, history=history, gameinfo=GameInfo(history), shell=Shell(), controls=Controls(), ui=UiSettings(), updater=Updater(), admin=Admin(),
                    health=Health(steamui), rules=GameRules(now, gamescope, monitor), tileStore=Tiles(),
                    battery=Battery(), media=Media(), backup=backup, artwork=Palette(), steamShortcuts=shortcuts, tasks=Tasks(), onboarding=Onboarding(), activity=Activity(), manuals=Manuals(), ludo=LudoSync(), trackpad=Trackpad(), cheats=Cheats(), layout=layout, emulatorControl=emulator_ctrl)
    pad = backends["pad"] = Pad()   # must stay referenced, like the rest
    backends["closer"] = Closer(pad, gamescope, now, backends["ui"])
    backends["thermal"] = Thermal(monitor, backends["ui"])
    backends["rules"].history = history
    for name, obj in backends.items():
        engine.rootContext().setContextProperty(name, obj)
    # closing the window only hides it: the app keeps listening for the AYN button and can bring itself back
    app.setQuitOnLastWindowClosed(False)
    install_signal_handlers(app, backends["ayn"])
    engine.load(QUrl.fromLocalFile(HERE + "/qml/Main.qml"))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    presentation = (monitor, gamescope, backends["admin"], backends["controls"], backends["health"], backends["media"])

    def update_presentation():
        active = window.property("presentationActive")
        for backend in presentation:
            backend.set_active(active)

    window.presentationActiveChanged.connect(update_presentation)
    update_presentation()
    if "--snapshot" in sys.argv:  # render the first frames to a PNG and exit, for docs and tests
        out = sys.argv[sys.argv.index("--snapshot") + 1]
        page = int(sys.argv[sys.argv.index("--page") + 1]) if "--page" in sys.argv else 0
        # a snapshot always shows a fixed game state, otherwise whatever ES-DE or Steam is doing at that moment throws the page
        # back to "Game": {"event": {...}} like ES-DE sends, or {"ui": [appid, "name"]} for Steam's UI; none means idle
        demo = json.loads(sys.argv[sys.argv.index("--demo") + 1]) if "--demo" in sys.argv else {}
        backends["nowPlaying"].pin(demo.get("event"), demo.get("ui"))
        window.setProperty("page", ["now", "apps", "system", "prefs", "tuning", "cheats", "manual", "graphs", "controls", "tasks", "stats", "info", "rules"][page] if page < 13 else "now")
        if "--step" in sys.argv:  # for screenshots of the first-run setup: jump to that step
            window.findChild(QObject, "onboarding").setProperty("step", int(sys.argv[sys.argv.index("--step") + 1]))
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
        if "--keep-demo" in sys.argv:  # show the keep-or-undo bar with 11 s left (nothing is changed or reverted)
            window.setProperty("tuningDemo", dict(active=True, seconds=11, total=CONFIRM_S, busy=False, recovery=False))
        if "--ask" in sys.argv:
            window.setProperty("askDemo", sys.argv[sys.argv.index("--ask") + 1])
        if "--notice" in sys.argv:  # code:title, show that popup message 600 ms in
            code, _, title = sys.argv[sys.argv.index("--notice") + 1].partition(":")
            if code == "hot":
                QTimer.singleShot(600, lambda: backends["thermal"].alert.emit(88, "Performance"))
            elif code.startswith("ts"):
                QTimer.singleShot(600, lambda: backends["controls"].notice.emit(code, ""))
            else:
                QTimer.singleShot(600, lambda: backends["steamShortcuts"].notice.emit(code, title))
        if "--ludo" in sys.argv:  # phase:title, show that Ludo banner 600 ms in (check | sync | start | upload)
            phase, _, title = sys.argv[sys.argv.index("--ludo") + 1].partition(":")
            QTimer.singleShot(600, lambda: backends["ludo"]._set(phase, title))
        if "--close-demo" in sys.argv:  # ms: hold Start + Select that many milliseconds in, with a pretend game in front
            closer = backends["closer"]
            closer.target = lambda: ([], "Demo Game")
            from .gamepad import BTN_SELECT, BTN_START, EVENT
            press = b"".join(EVENT.pack(0, 0, 1, code, 1) for code in (BTN_SELECT, BTN_START))
            QTimer.singleShot(int(sys.argv[sys.argv.index("--close-demo") + 1]), lambda: backends["pad"].feed("demo", press))
        delay = int(sys.argv[sys.argv.index("--delay") + 1]) if "--delay" in sys.argv else 3000
        QTimer.singleShot(delay, lambda: (print("dimmed:", window.property("dimmed")), QQuickWindow.grabWindow(window).save(out), app.quit()))
    try:
        return app.exec()
    finally:
        # Destroy the window and its bindings while the context backends are still alive.
        shiboken6.delete(engine)
