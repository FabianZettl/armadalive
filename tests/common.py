"""Shared set-up: Qt without a display, and a small fake ES-DE folder so the tests do not depend on anybody's collection."""
import os, sys, tempfile, time
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ESDE = tempfile.mkdtemp(prefix="armadalive-esde-")
os.environ["ARMADALIVE_ESDE_DIR"] = ESDE   # read when armadalive.nowplaying is imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool, Signal  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def touch(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as file:
        file.write(text)


# one game with a logo, a background and a gamelist entry
touch(f"{ESDE}/downloaded_media/snes/marquees/Super Game (EU).png")
touch(f"{ESDE}/downloaded_media/snes/fanart/Super Game (EU).jpg")
touch(f"{ESDE}/downloaded_media/snes/manuals/Super Game (EU).pdf")
touch(f"{ESDE}/gamelists/snes/gamelist.xml", """<gameList><game><path>./Super Game (EU).zip</path><name>Super Game</name>
<desc>A test game.</desc><rating>0.8</rating><releasedate>19951231T000000</releasedate><developer>Dev</developer>
<genre>Platform</genre><players>1-2</players><playcount>6</playcount><gametime>7260</gametime></game></gameList>""")
ROMS = "/run/media/armada/EXT/Emulation/roms"
GAME = dict(event="game-select", system="snes", name="x", path=f"{ROMS}/snes/Super Game (EU).zip", t=1)


class Fake(QObject):
    """Stands in for Gamescope and SteamUi: only the signals NowPlaying listens to."""
    focusChanged = Signal(str)
    selected = Signal(object, str)
    state = {"focus": ""}


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Asynchronous update did not arrive")


def dispose_qt(obj):
    # Keep the parent alive through queued signal emission and delete its timers on their owner.
    if not QThreadPool.globalInstance().waitForDone(5000):
        raise AssertionError("Runtime workers did not finish before fixture teardown")
    obj.deleteLater()
    app.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


@contextmanager
def runtime_object(obj):
    try:
        yield obj
    finally:
        dispose_qt(obj)
