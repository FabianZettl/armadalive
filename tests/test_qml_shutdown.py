"""Exercise shutdown with the complete interface and its real backends."""
import os
import signal
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest import mock


class QmlShutdown(unittest.TestCase):
    def test_normal_quit_releases_qml_before_backends(self):
        self.check_shutdown("quit", 0)

    def test_sigterm_releases_qml_before_backends(self):
        self.check_shutdown("terminate", 143)

    def check_shutdown(self, mode, exit_code):
        with TemporaryDirectory() as home:
            result = subprocess.run(
                [sys.executable, "-m", "tests.test_qml_shutdown", "--child", mode, "--windowed"],
                env=dict(os.environ, HOME=home, ARMADALIVE_ESDE_DIR=os.path.join(home, "esde"),
                         QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software"),
                capture_output=True, text=True, timeout=10,
            )
        self.assertNotRegex(result.stderr, r"TypeError: Cannot read property .* of null")
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)


def child(mode):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import qmlEngine
    from shiboken6 import isValid

    from armadalive import app

    retained_engines = []

    class Application(QGuiApplication):
        def exec(self):
            window, = self.topLevelWindows()
            assert window.isVisible()
            assert window.setProperty("page", "system")
            # Keep a second reference across main()'s return to exercise explicit teardown.
            retained_engines.append(qmlEngine(window))
            if mode == "quit":
                QTimer.singleShot(0, self.quit)
            else:
                QTimer.singleShot(0, lambda: os.kill(os.getpid(), signal.SIGTERM))
            return super().exec()

    with mock.patch.object(app, "QGuiApplication", Application):
        status = app.main()
    assert not isValid(retained_engines[0]), "The QML engine outlived main()"
    return status


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child(sys.argv[2]))
    unittest.main()
