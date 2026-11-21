import json, os, shlex, tempfile, threading, unittest
from types import SimpleNamespace
from unittest import mock

from tests.common import QObject, Signal, delete_qobject, wait_for
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

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


class Coordinator(unittest.TestCase):
    make = Add.make
    GAME = Add.GAME

    def test_worker_finishes_silently_after_its_parent_is_deleted(self):
        parent = QObject()
        shortcuts = ss.SteamShortcuts(parent=parent)
        started, release = threading.Event(), threading.Event()
        workers, failures = [], []

        def resolve(*_):
            workers.append(threading.current_thread())
            started.set()
            release.wait(3)
            return None

        with mock.patch.object(threading, 'excepthook', failures.append):
            shortcuts.launch('Mario', 'nes', ROM, resolve, lambda: True)
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(shortcuts.state['busy'])
            finally:
                delete_qobject(parent)
                release.set()
                if workers:
                    workers[0].join(1)
            self.assertFalse(workers[0].is_alive())
        self.assertEqual([str(failure.exc_value) for failure in failures], [])

    def test_stalled_socket_releases_the_launch_at_its_dispatch_deadline(self):
        from tests.test_steamui_target import Socket

        c = self.make(self.GAME)
        socket = Socket()
        with mock.patch.object(ss, 'PREPARE_TIMEOUT_MS', 25), \
                mock.patch.object(steamui, 'QWebSocket', return_value=socket), \
                mock.patch.object(steamui, '_discover', side_effect=lambda _, done: done('ws://fixture')):
            try:
                c.launch_steam('12', 'Native', lambda: True)
                self.assertTrue(c.state['busy'])
                self.assertEqual(socket.opened, ['ws://fixture'])
                QTest.qWait(150)
                self.assertFalse(c.state['busy'])
                self.assertEqual(c.notices, ['launchFailed'])
                self.assertNotIn(socket, steamui._live)
                self.assertEqual(socket.sent, [])
            finally:
                if socket in steamui._live:
                    socket.errorOccurred.emit()

    def test_sent_launch_can_be_acknowledged_after_the_dispatch_deadline(self):
        from tests.test_steamui_target import Socket

        c = self.make(self.GAME)
        clock = [10.0]
        socket = Socket()
        monotonic = SimpleNamespace(monotonic=lambda: clock[0])
        with mock.patch.object(ss, 'time', monotonic), \
                mock.patch.object(steamui, 'time', monotonic), \
                mock.patch.object(ss, 'PREPARE_TIMEOUT_MS', 25), \
                mock.patch.object(steamui, 'QWebSocket', return_value=socket), \
                mock.patch.object(steamui, '_discover', side_effect=lambda _, done: done('ws://fixture')):
            c.launch_steam('12', 'Native', lambda: True)
            socket.connected.emit()
            self.assertEqual(len(socket.sent), 1)
            clock[0] = 10.15
            QTest.qWait(150)
            self.assertTrue(c.state['busy'])
            socket.textMessageReceived.emit(json.dumps({'id': 7, 'result': {'result': {'value': True}}}))
            self.assertEqual(c.notices, ['launchRequested'])
            self.assertFalse(c.state['busy'])

    def test_launch_and_add_share_admission_and_failure_allows_retry(self):
        c = self.make(self.GAME)
        calls, resolutions = [], []
        def resolve(*_):
            resolutions.append(threading.get_ident())
            return ['/usr/bin/emu', ROM]
        with mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: calls.append((script, done))), \
                mock.patch.object(ss, 'launch_command', return_value=['/usr/bin/emu', ROM]), \
                mock.patch.object(ss, 'shortcut_launches', return_value=[]), \
                mock.patch.object(ss, 'known_appid', return_value=123):
            c.launch_steam('12', 'Native', lambda: True)
            c.launch('Mario', 'nes', ROM, resolve, lambda: True)
            c.add()
            self.assertEqual(len(calls), 1)
            self.assertEqual(resolutions, [])
            calls[0][1](False)
            self.assertEqual(c.notices, ['launchFailed'])
            self.assertFalse(c.state['busy'])
            c.launch('Mario', 'nes', ROM, resolve, lambda: True)
            wait_for(lambda: len(calls) == 2)
            c.launch_steam('12', 'Native', lambda: True)
            c.add()
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(resolutions[0], threading.get_ident())
            calls[1][1](True)
            self.assertEqual(c.notices, ['launchFailed', 'launchRequested'])

    def test_add_responses_accept_only_nonzero_signed_or_unsigned_shortcut_ids(self):
        c = self.make(self.GAME)
        for value in (None, False, True, 0, 1.5, '123', -(1 << 31) - 1, 1 << 32, -(1 << 31), -1, 1, 0xffffffff):
            with self.subTest(value=value), \
                    mock.patch.object(ss, 'launch_command', return_value=['/usr/bin/emu', ROM]), \
                    mock.patch.object(ss, 'shortcut_launches', return_value=[]), \
                    mock.patch.object(ss, 'artwork', return_value=[]), \
                    mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: done(value)):
                c._recent.clear()
                c.notices.clear()
                c.add()
                wait_for(lambda: bool(c.notices))
                valid = type(value) is int and -(1 << 31) <= value <= 0xffffffff and value != 0
                self.assertEqual(c.notices, ['created' if valid else 'unreachable'])

    def test_creation_is_remembered_even_if_focus_changed_before_confirmation(self):
        c = self.make(self.GAME)
        calls = []
        with mock.patch.object(ss, 'launch_command', return_value=['/usr/bin/emu', ROM]), \
                mock.patch.object(ss, 'shortcut_launches', return_value=[]), \
                mock.patch.object(ss, 'artwork', return_value=[]), \
                mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: calls.append(done)):
            c.add()
            wait_for(lambda: bool(calls))
            c._np.state = {'kind': 'idle'}
            c._np.changed.emit()
            calls[0](123)
            c._np.state = self.GAME
            c._np.changed.emit()
            c.add()
            wait_for(lambda: bool(c.notices) or len(calls) > 1)
            self.assertEqual(c.notices, ['exists'])
            self.assertEqual(len(calls), 1)

    def test_adding_another_game_retains_the_first_confirmed_shortcut(self):
        c = self.make(self.GAME)
        calls = []

        def dispatch(script, done, **_):
            calls.append(script)
            done(100 + len(calls))

        with mock.patch.object(ss, 'launch_command', side_effect=lambda _, path: ['/usr/bin/emu', path]), \
                mock.patch.object(ss, 'shortcut_launches', return_value=[]), \
                mock.patch.object(ss, 'artwork', return_value=[]), \
                mock.patch.object(ss, 'eval_js', side_effect=dispatch):
            for count, path in enumerate((ROM, '/roms/other.zip', ROM), 1):
                c._np.state = {**self.GAME, 'path': path}
                c._np.changed.emit()
                c.add()
                wait_for(lambda: len(c.notices) == count)
        self.assertEqual(c.notices, ['created', 'created', 'exists'])
        self.assertEqual(len(calls), 2)

    def test_signed_existing_id_is_normalized_and_newly_created_id_is_reused(self):
        c = self.make(self.GAME)
        calls = []
        with mock.patch.object(ss, 'known_appid', return_value=-1), \
                mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: calls.append((script, done))):
            c.launch('Mario', 'nes', ROM, lambda *_: ['/usr/bin/emu', ROM], lambda: True)
            wait_for(lambda: bool(calls))
            self.assertIn(f'RunGame("{(0xffffffff << 32) | 0x02000000}"', calls[0][0])
            calls[0][1](True)
        with mock.patch.object(ss, 'launch_command', return_value=['/usr/bin/emu', ROM]), \
                mock.patch.object(ss, 'shortcut_launches', return_value=[]), \
                mock.patch.object(ss, 'artwork', return_value=[]), \
                mock.patch.object(ss, 'known_appid', return_value=None), \
                mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: calls.append((script, done))):
            c.add()
            wait_for(lambda: len(calls) == 2)
            calls[-1][1](-2)
            c.launch('Mario', 'nes', ROM, lambda *_: ['/usr/bin/emu', ROM], lambda: True)
            wait_for(lambda: len(calls) == 3)
            self.assertIn(f'RunGame("{(0xfffffffe << 32) | 0x02000000}"', calls[-1][0])
            calls[-1][1](True)

    def test_new_shortcut_is_not_launched_after_its_catalog_entry_becomes_obsolete(self):
        c = self.make(self.GAME)
        current, calls, delayed = [True], [], []
        with mock.patch.object(ss, 'known_appid', return_value=None), \
                mock.patch.object(ss, 'artwork', return_value=[]), \
                mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: calls.append((script, done))):
            c.launch('Mario', 'nes', ROM, lambda *_: ['/usr/bin/emu', ROM], lambda: current[0])
            wait_for(lambda: bool(calls))
            with mock.patch.object(ss.QTimer, 'singleShot', side_effect=lambda delay, owner, callback: delayed.append(callback)):
                calls[0][1](123)
            current[0] = False
            delayed[0]()
            self.assertEqual(len(calls), 1)
            self.assertFalse(c.state['busy'])
            self.assertEqual(c.notices, [])

    def test_delayed_new_shortcut_launch_cannot_renew_an_expired_dispatch_deadline(self):
        from tests.test_steamui_target import Socket
        c = self.make(self.GAME)
        socket, discovered, delayed = Socket(), [], []
        clock = [10.0]
        with mock.patch.object(ss, 'time', SimpleNamespace(monotonic=lambda: clock[0])), \
                mock.patch.object(ss, 'known_appid', return_value=None), \
                mock.patch.object(ss, 'artwork', return_value=[]), \
                mock.patch.object(steamui, 'QWebSocket', return_value=socket), \
                mock.patch.object(steamui, '_discover', side_effect=lambda shared, done: discovered.append(done)):
            with mock.patch.object(ss, 'eval_js', side_effect=lambda script, done, **_: done(123)), \
                    mock.patch.object(ss.QTimer, 'singleShot', side_effect=lambda delay, owner, callback: delayed.append(callback)):
                c.launch('Mario', 'nes', ROM, lambda *_: ['/usr/bin/emu', ROM], lambda: True)
                wait_for(lambda: bool(delayed))
            clock[0] = 20.0
            delayed[0]()
            if discovered:
                discovered[0]('ws://fixture')
                socket.connected.emit()
            self.assertEqual(socket.sent, [])
            self.assertFalse(c.state['busy'])
            self.assertEqual(c.notices, ['launchFailed'])

    def test_preparation_deadline_is_rechecked_after_discovery_and_connection(self):
        from tests.test_steamui_target import Socket
        c = self.make(self.GAME)
        socket, discovered = Socket(), []
        clock = [10.0]
        monotonic = SimpleNamespace(monotonic=lambda: clock[0])
        with mock.patch.object(ss, 'time', monotonic), \
                mock.patch.object(steamui, 'time', monotonic), \
                mock.patch.object(ss, 'known_appid', return_value=123), \
                mock.patch.object(steamui, 'QWebSocket', return_value=socket), \
                mock.patch.object(steamui, '_discover', side_effect=lambda shared, done: discovered.append(done)):
            c.launch('Mario', 'nes', ROM, lambda *_: ['/usr/bin/emu', ROM], lambda: True)
            wait_for(lambda: bool(discovered))
            discovered[0]('ws://fixture')
            clock[0] = 15.0
            socket.connected.emit()
            self.assertEqual(socket.sent, [])
            self.assertFalse(c.state['busy'])
            self.assertEqual(c.notices, ['launchFailed'])

    def test_creation_awaits_properties_and_all_artwork_before_reporting_id(self):
        # The runtime result is requested with awaitPromise; the script itself must
        # await Steam's property promises before returning the shortcut identifier.
        for method in ('SetShortcutName', 'SetShortcutExe', 'SetShortcutStartDir', 'SetShortcutLaunchOptions', 'SetCustomArtworkForApp'):
            self.assertIn('await A.' + method, ss.ADD_JS)
        self.assertIn('!Number.isInteger(id)', ss.ADD_JS)
        self.assertIn('id === 0', ss.ADD_JS)


class LogCache(unittest.TestCase):
    def test_log_growth_during_read_cannot_make_the_cache_unbounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'es_log.txt')
            with open(path, 'wb') as stream:
                stream.write(b'x' * 2_100_000)
            stale_stat = SimpleNamespace(st_mtime_ns=123, st_size=1)
            with mock.patch.object(ss, 'LOG', path), mock.patch.object(ss.os, 'stat', return_value=stale_stat):
                cached = ss._read_log(('', 0, 0))
            self.assertLessEqual(len(cached[0]), 2_000_000)


    def test_log_tail_is_bounded_cached_and_tolerates_partial_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'es_log.txt')
            with open(path, 'wb') as stream:
                stream.write(b'x' * 10 + b'\xe2\x82\xac' + b'y' * 1_999_999)
            with mock.patch.object(ss, 'LOG', path):
                cached = ss._read_log(('', 0, 0))
                self.assertLessEqual(len(cached[0]), 2_000_000)
                with mock.patch('builtins.open', side_effect=AssertionError('unchanged file was reopened')):
                    self.assertIs(ss._read_log(cached), cached)
                os.unlink(path)
                self.assertEqual(ss._read_log(cached), ('', 0, 0))

if __name__ == "__main__":
    unittest.main()
