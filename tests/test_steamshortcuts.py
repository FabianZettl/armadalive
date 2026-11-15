import json, os, shlex, tempfile, threading, unittest
from types import SimpleNamespace
from unittest import mock

from tests.common import QObject, Signal, delete_qobject, wait_for
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage

from armadalive import steamshortcuts as ss, steamui

ROM = "/run/media/armada/EXT/Emulation/roms/nes/Super Mario Bros. 3 (Europe).zip"
LOG = f"""Oct 29 16:07:09 Info:   Launching game "Super Mario Bros. 3" from system "nes"...
Oct 29 16:07:09 Info:   Expanded emulator launch command:
Oct 29 16:07:09 Info:   /var/lib/flatpak/exports/bin/org.libretro.RetroArch -L /cores/mesen_libretro.so {shlex.quote(ROM)}
Oct 29 16:15:57 Info:   Expanded emulator launch command:
Oct 29 16:15:57 Info:   /home/armada/.local/bin/eden-turnip -f -g /roms/switch/Ys\\ Origin.nsp
"""


class Launch(unittest.TestCase):
    def test_the_command_that_started_this_rom_is_found(self):
        words = ss.launch_command(LOG, ROM)
        self.assertEqual(words[0], "/var/lib/flatpak/exports/bin/org.libretro.RetroArch")
        self.assertEqual(words[-1], ROM)

    def test_unknown_rom_and_empty_log_give_nothing(self):
        self.assertIsNone(ss.launch_command(LOG, "/roms/never-started.zip"))
        self.assertIsNone(ss.launch_command("", ROM))

    def test_newest_command_wins(self):
        log = LOG + f"Oct 29 17:00:00 Info:   Expanded emulator launch command:\nOct 29 17:00:00 Info:   /usr/bin/other {shlex.quote(ROM)}\n"
        self.assertEqual(ss.launch_command(log, ROM)[0], "/usr/bin/other")

    def test_options_keep_the_arguments_intact_through_a_shell(self):
        words = ss.launch_command(LOG, ROM)
        options = ss.options_for(words)
        self.assertTrue(options.startswith(f"{ss.WRAP} %command% -L /cores/mesen_libretro.so "))
        self.assertEqual(shlex.split(options)[2:], words[1:])


class Existing(unittest.TestCase):
    def test_launch_options_are_read_from_the_binary_shortcuts_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "shortcuts.vdf")
            open(f, "wb").write(b"\x00shortcuts\x00\x000\x00\x01AppName\x00A\x00\x01LaunchOptions\x00wrap %command% -g x\x00\x08\x08")
            with mock.patch.object(ss, "SHORTCUTS", f):
                self.assertEqual(ss.shortcut_launches(), ["wrap %command% -g x"])


class Artwork(unittest.TestCase):
    def test_cover_hero_and_logo_are_found_by_the_rom_name(self):
        with tempfile.TemporaryDirectory() as d:
            for kind, ext in (("covers", "jpg"), ("fanart", "jpg"), ("marquees", "png")):
                os.makedirs(f"{d}/nes/{kind}")
                img = QImage(40, 20, QImage.Format.Format_RGB32)
                img.fill(QColor("#336699"))
                img.save(f"{d}/nes/{kind}/Super Mario Bros. 3 (Europe).{ext}")
            with mock.patch.object(ss, "MEDIA", d), mock.patch.object(ss, "QImage", wraps=QImage) as decode:
                art = ss.artwork("nes", ROM)
            self.assertEqual(sum("/fanart/" in args[0] for args, _ in decode.call_args_list), 1)
            self.assertEqual(sorted(a[0] for a in art), [0, 1, 2, 3])
            self.assertTrue(all(a[1] for a in art))
            with mock.patch.object(ss, "MEDIA", "/nonexistent"):
                self.assertEqual(ss.artwork("nes", ROM), [])


class Now(QObject):
    changed = Signal()
    legacyRulesChanged = Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state


def close_shortcuts(shortcuts):
    for timer in shortcuts.findChildren(QTimer):
        timer.stop()
    shortcuts._request = None
    wait_for(lambda: shortcuts._preparing is None)
    delete_qobject(shortcuts)


class Add(unittest.TestCase):
    def make(self, state):
        np = Now(state)
        with mock.patch.object(ss, "launch_command", return_value=None):
            c = ss.SteamShortcuts(np)
        self.addCleanup(close_shortcuts, c)
        c.notices = []
        c.notice.connect(lambda code, title: c.notices.append(code))
        return c

    GAME = dict(kind="game", title="Mario 3", path=ROM, system="nes")

    def test_without_a_logged_command_the_user_is_told_to_start_the_game_first(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=None):
            c.add()
            wait_for(lambda: bool(c.notices))
        self.assertEqual(c.notices, ["unknown"])

    def test_an_existing_shortcut_is_not_added_twice(self):
        c = self.make(self.GAME)
        words = ["/usr/bin/emu", ROM]
        with mock.patch.object(ss, "launch_command", return_value=words), \
                mock.patch.object(ss, "shortcut_launches", return_value=[ss.options_for(words)]), \
                mock.patch.object(ss, "eval_js") as run:
            c.add()
            wait_for(lambda: bool(c.notices))
        self.assertEqual(c.notices, ["exists"])
        run.assert_not_called()

    def test_a_new_shortcut_is_sent_to_steam_and_reported(self):
        c = self.make(self.GAME)
        words = ["/usr/bin/emu", ROM]
        sent = {}
        with mock.patch.object(ss, "launch_command", return_value=words), mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: sent.update(js=js, done=done)):
            c.add()
            c.add()   # a second tap while Steam is busy does nothing
            wait_for(lambda: bool(sent))
        self.assertIn("Mario 3", sent["js"])
        self.assertIn(shlex.quote(ROM).strip("'"), sent["js"].replace("\\\\", "\\"))
        sent["done"](123)
        self.assertEqual(c.notices, ["created"])

    def test_steam_not_reachable_is_reported(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: done(None)):
            c.add()
            wait_for(lambda: bool(c.notices))
        self.assertEqual(c.notices, ["unreachable"])

    def test_rejected_steam_response_does_not_report_creation(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), \
                mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: done(False)):
            c.add()
            wait_for(lambda: bool(c.notices))
        self.assertEqual(c.notices, ["unreachable"])

    def test_preparation_failure_leaves_the_action_available_to_retry(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", side_effect=[OSError("read failed"), []]), \
                mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: done(123)) as dispatch:
            with self.assertLogs(ss.log, "ERROR"):
                c.add()
                wait_for(lambda: c.notices == ["prepareFailed"])
            self.assertFalse(c.state.get("busy"))
            dispatch.assert_not_called()
            c.add()
            wait_for(lambda: c.notices == ["prepareFailed", "created"])

    def test_late_steam_reply_does_not_notify_for_a_changed_game(self):
        c = self.make(self.GAME)
        replies = []
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), \
                mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: replies.append(done)):
            c.add()
            wait_for(lambda: bool(replies))
            c._np.state = {**self.GAME, "path": "/roms/other.zip"}
            c._np.changed.emit()
            replies[0](123)
        self.assertFalse(c.state.get("busy"))
        self.assertEqual(c.notices, [])

    def test_second_add_reuses_the_confirmed_creation_before_steam_writes_its_file(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), \
                mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: done(123)) as dispatch:
            c.add()
            wait_for(lambda: c.notices == ["created"])
            c.add()
            wait_for(lambda: c.notices == ["created", "exists"])
        dispatch.assert_called_once()

    def test_stalled_preparation_reports_failure_without_creating_a_second_worker(self):
        c = self.make(self.GAME)
        started, release = threading.Event(), threading.Event()

        def artwork(*_):
            started.set()
            release.wait(2)
            return []

        with mock.patch.object(ss, "PREPARE_TIMEOUT_MS", 30, create=True), \
                mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", side_effect=artwork) as prepare, \
                mock.patch.object(ss, "eval_js") as dispatch:
            try:
                c.add()
                wait_for(started.is_set)
                wait_for(lambda: c.notices == ["prepareFailed"])
                self.assertTrue(c.state.get("busy"))
                c.add()
            finally:
                release.set()
            wait_for(lambda: not c.state.get("busy"))
            prepare.assert_called_once()
            dispatch.assert_not_called()

    def test_result_at_the_monotonic_deadline_is_not_dispatched_before_the_qt_timer(self):
        c = self.make(self.GAME)
        ready = threading.Event()
        c._prepared.connect(lambda *_: ready.set(), Qt.ConnectionType.DirectConnection)
        clock = [10.0]
        with mock.patch.object(ss, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                mock.patch.object(ss, "PREPARE_TIMEOUT_MS", 5000), \
                mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), \
                mock.patch.object(ss, "eval_js", side_effect=lambda js, done, **_: done(123)) as dispatch:
            c.add()
            self.assertTrue(ready.wait(1))
            clock[0] = 15.0  # the worker result is queued; the Qt timer has yet to fire
            wait_for(lambda: bool(c.notices))
            dispatch.assert_not_called()
        self.assertEqual(c.notices, ["prepareFailed"])
        self.assertFalse(c.state["busy"])

    def test_game_change_after_discovery_starts_never_sends_add_shortcut(self):
        class Socket(QObject):
            connected = Signal()
            disconnected = Signal()
            textMessageReceived = Signal(str)
            errorOccurred = Signal()

            def open(self, url):
                opened.append(url.toString())

            def sendTextMessage(self, message):
                sent.append(json.loads(message)["params"]["expression"])

            def abort(self):
                pass

        for discovery_first in (False, True):
            with self.subTest(discovery_first=discovery_first):
                c = self.make(self.GAME)
                socket = Socket()
                discovered, opened, sent = [], [], []
                with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                        mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                        mock.patch.object(ss, "artwork", return_value=[]), \
                        mock.patch.object(steamui, "QWebSocket", return_value=socket), \
                        mock.patch.object(steamui, "_discover", side_effect=lambda shared, done: discovered.append(done)):
                    c.add()
                    wait_for(lambda: bool(discovered))
                    if discovery_first:
                        discovered[0]("ws://localhost/fixture")
                    c._np.state = {"kind": "idle"}
                    c._np.changed.emit()
                    if not discovery_first:
                        discovered[0]("ws://localhost/fixture")
                    self.assertEqual(opened, ["ws://localhost/fixture"])
                    socket.connected.emit()
                    self.assertNotIn(socket, steamui._live)
                    self.assertFalse(c.state["busy"])
                    self.assertFalse(sent, "Stale AddShortcut reached the socket")
                    self.assertEqual(c.notices, [])

    def test_game_change_while_preparing_does_not_publish_or_dispatch_a_stale_action(self):
        c = self.make(self.GAME)
        started, release = threading.Event(), threading.Event()

        def artwork(*_):
            started.set()
            release.wait(1.5)
            return []

        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", artwork), \
                mock.patch.object(ss, "eval_js") as dispatch:
            try:
                c.add()
                wait_for(started.is_set)
                self.assertTrue(c.state.get("busy"))
                c._np.state = {**self.GAME, "path": "/roms/other.zip"}
                c._np.changed.emit()
                c._np.state = self.GAME
                c._np.changed.emit()
            finally:
                release.set()
            wait_for(lambda: not c.state.get("busy"))
            dispatch.assert_not_called()
        self.assertEqual(c.notices, [])


class LaunchRules(unittest.TestCase):
    def setUp(self):
        self.now = Now(Add.GAME)
        self.rule_status = None
        self.current = True
        self.rule_checks, self.steam_calls, self.notices = [], [], []
        self.shortcuts = ss.SteamShortcuts(self.now, prepare_esde_launch=self.prepare_rule)
        self.shortcuts.notice.connect(lambda code, detail: self.notices.append((code, detail)))
        self.now.legacyRulesChanged.connect(self.shortcuts.resume_esde_launch)
        self.owner = threading.get_ident()
        self.enterContext(mock.patch.object(ss, "eval_js", side_effect=self.eval_script))
        self.enterContext(mock.patch.object(ss, "artwork", return_value=[]))
        self.addCleanup(close_shortcuts, self.shortcuts)

    def prepare_rule(self, system, path, title):
        self.rule_checks.append((threading.get_ident(), system, path, title))
        return self.rule_status

    def eval_script(self, script, done, *, valid):
        self.steam_calls.append((script, done, valid))

    def launch(self, *, appid=123):
        with mock.patch.object(ss, "known_appid", return_value=appid):
            self.shortcuts.launch("Mario 3", "nes", ROM, lambda *_: ["/usr/bin/emu", ROM], lambda: self.current)
            wait_for(lambda: self.rule_checks or self.steam_calls)
        self.assertEqual(self.rule_checks, [(self.owner, "nes", ROM, "Mario 3")])

    def test_pending_rule_blocks_both_shortcut_creation_and_existing_shortcut_launch(self):
        for appid, expression in ((None, "AddShortcut"), (123, "RunGame")):
            with self.subTest(appid=appid):
                self.rule_status = None
                self.rule_checks.clear()
                self.steam_calls.clear()
                self.launch(appid=appid)
                self.assertTrue(self.shortcuts.state["busy"])
                self.assertFalse(self.steam_calls)
                self.rule_status = ""
                self.now.legacyRulesChanged.emit()
                self.now.legacyRulesChanged.emit()
                self.assertEqual(len(self.steam_calls), 1)
                script, done, valid = self.steam_calls[0]
                self.assertIn(expression, script)
                self.assertTrue(valid())
                # Settle this fixture without running the new-shortcut follow-up.
                done(None)

    def test_a_pending_rule_resolves_at_the_deadline_without_starting_steam(self):
        clock = [10.0]
        with mock.patch.object(ss, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                mock.patch.object(ss, "PREPARE_TIMEOUT_MS", 5000):
            self.launch()
            clock[0] = 15.0
            self.rule_status = ""
            self.now.legacyRulesChanged.emit()
        self.assertFalse(self.steam_calls)
        self.assertFalse(self.shortcuts.state["busy"])
        self.assertEqual(self.notices, [("prepareFailed", "Mario 3")])

    def test_pending_rule_without_a_proof_signal_times_out(self):
        with mock.patch.object(ss, "PREPARE_TIMEOUT_MS", 120):
            self.launch()
            wait_for(lambda: not self.shortcuts.state["busy"])
        self.assertFalse(self.steam_calls)
        self.assertEqual(self.notices, [("prepareFailed", "Mario 3")])

    def test_proof_signal_cannot_resume_a_stale_launch(self):
        self.launch()
        self.current = False
        self.rule_status = ""
        self.now.legacyRulesChanged.emit()
        self.assertFalse(self.steam_calls)
        self.assertFalse(self.notices)
        self.assertEqual(len(self.rule_checks), 1)
        self.assertFalse(self.shortcuts.state["busy"])

    def test_rule_error_blocks_launch_and_reaches_the_notice(self):
        self.rule_status = "Could not apply emulator resolution"
        self.launch()
        self.assertFalse(self.steam_calls)
        self.assertFalse(self.shortcuts.state["busy"])
        self.assertEqual(self.notices, [("launchBlocked", self.rule_status)])

    def test_proof_can_become_pending_again_before_the_socket_actually_sends(self):
        self.rule_status = ""
        self.launch()
        _, done, valid = self.steam_calls[0]
        self.rule_status = None
        self.assertFalse(valid())
        done(None)
        self.assertTrue(self.shortcuts.state["busy"])
        self.assertFalse(self.notices)
        self.rule_status = ""
        self.now.legacyRulesChanged.emit()
        self.now.legacyRulesChanged.emit()
        self.assertEqual(len(self.steam_calls), 2)
        _, done, valid = self.steam_calls[-1]
        self.assertTrue(valid())
        done(True)
        self.assertEqual(self.notices, [("launchRequested", "Mario 3")])

    def test_first_shortcut_launch_checks_rules_again_before_run_game(self):
        self.rule_status = ""
        self.launch(appid=None)
        script, created, valid = self.steam_calls[0]
        self.assertIn("AddShortcut", script)
        self.assertTrue(valid())
        self.rule_status = None
        created(123)
        wait_for(lambda: len(self.rule_checks) == 3)
        self.assertEqual(len(self.steam_calls), 1)
        self.rule_status = ""
        self.now.legacyRulesChanged.emit()
        self.assertEqual(len(self.steam_calls), 2)
        script, done, valid = self.steam_calls[1]
        self.assertIn("RunGame", script)
        self.assertTrue(valid())
        done(True)
        self.assertEqual(self.notices, [("launchRequested", "Mario 3")])

    def test_add_to_steam_without_launching_does_not_prepare_emulator_rules(self):
        self.rule_status = "Could not apply emulator resolution"
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), \
                mock.patch.object(ss, "shortcut_launches", return_value=[]):
            self.shortcuts.add()
            wait_for(lambda: bool(self.steam_calls))
        script, done, valid = self.steam_calls[0]
        self.assertIn("AddShortcut", script)
        self.assertTrue(valid())
        done(123)
        self.assertEqual(self.rule_checks, [])
        self.assertEqual(self.notices, [("created", "Mario 3")])

    def test_native_steam_launch_does_not_prepare_emulator_rules(self):
        self.shortcuts.launch_steam(12, "Native", lambda: True)
        script, done, valid = self.steam_calls[0]
        self.assertIn('RunGame("12"', script)
        self.assertTrue(valid())
        done(True)
        self.assertEqual(self.rule_checks, [])


if __name__ == "__main__":
    unittest.main()
