"""Run the application's signal binding against a test-owned Qt process."""
import os
import select
import signal
import subprocess
import sys
import time

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from armadalive.app import install_signal_handlers


class Button(QObject):
    pressed = Signal()
    released = Signal()


def child_app(directory, mode, release):
    app = QCoreApplication([])
    button = Button()
    button.pressed.connect(lambda: (directory / "button-pressed").touch())
    button.released.connect(lambda: (directory / "button-released").touch())
    install_signal_handlers(app, button)

    def mark_quit():
        (directory / "about-to-quit").touch()
        if mode != "blocked":
            release.set()

    app.aboutToQuit.connect(mark_quit)
    return app


def gate_write(real_write, entered, release):
    def write(*args, **kwargs):
        entered.set()
        release.wait(30)
        real_write(*args, **kwargs)
    return write


def exec_child(app, mode, entered):
    if not entered.wait(2):
        raise RuntimeError("Child write did not start")
    print("accepted", flush=True)
    if mode in ("quit", "export"):
        QTimer.singleShot(0, app.quit)
    return app.exec()


def _wait_for_file(test, path):
    deadline = time.monotonic() + 2
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    test.assertTrue(path.exists(), f"{path.name} was not written")


def run_child(test, module, directory, mode, signum=None, *, button_signals=False):
    env = dict(os.environ, HOME=str(directory), ARMADALIVE_ESDE_DIR=str(directory / "esde"))
    command = [sys.executable, "-m", module, "--child", str(directory), mode]
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        try:
            test.assertTrue(select.select([proc.stdout], [], [], 5)[0], "Child did not accept the write")
            test.assertEqual(proc.stdout.readline().strip(), "accepted")
            if button_signals:
                proc.send_signal(signal.SIGUSR1)
                _wait_for_file(test, directory / "button-pressed")
                test.assertFalse((directory / "button-released").exists())
                proc.send_signal(signal.SIGUSR2)
                _wait_for_file(test, directory / "button-released")
            if signum is not None:
                proc.send_signal(signum)
            _, stderr = proc.communicate(timeout=6)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    test.assertEqual(proc.returncode, 128 + signum if signum is not None else 0, stderr)
    test.assertTrue((directory / "about-to-quit").exists())
    return stderr
