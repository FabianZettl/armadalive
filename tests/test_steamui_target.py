import json, unittest
from types import SimpleNamespace
from unittest import mock

from tests.common import app, delete_qobject  # noqa: F401
from armadalive import steamui


def pages(*titles):
    return [dict(type="page", title=t, webSocketDebuggerUrl=f"ws://x/{i}") for i, t in enumerate(titles)]


class Target(unittest.TestCase):
    def find(self, titles, shared=False):
        return steamui._target(pages(*titles), shared)

    def test_discovery_is_requested_without_reading_the_socket_on_the_owner_thread(self):
        fetch = mock.patch("urllib.request.urlopen", side_effect=AssertionError("synchronous discovery"))
        with fetch as open_url, mock.patch.object(steamui, "_discover", side_effect=lambda shared, done: done(None)):
            ui = steamui.SteamUi()
            self.addCleanup(delete_qobject, ui)
            for _ in range(4):
                ui._tick()
            open_url.assert_not_called()

    def test_shared_context_discovery_does_not_complete_inline(self):
        completed = []
        with mock.patch.object(steamui, "LIST_URL", "http://127.0.0.1:0/json"):
            steamui.eval_js("1", completed.append, timeout=100)
        self.assertEqual(completed, [])
        from PySide6.QtTest import QTest
        QTest.qWait(150)
        self.assertEqual(completed, [None])

    def test_late_focus_reply_cannot_replace_the_current_selection(self):
        ui = steamui.SteamUi()
        self.addCleanup(delete_qobject, ui)
        selected = []
        ui.selected.connect(lambda appid, name: selected.append((appid, name)))

        def reply(request_id, appid):
            return json.dumps({"id": request_id, "result": {"result": {"value": json.dumps({"appid": appid})}}})

        ui._request_id = 5
        ui._reply(reply(5, 200))
        ui._reply(reply(4, 100))
        self.assertEqual(selected, [(200, "")])

    def test_busy_discovery_coalesces_ticks_then_retries_after_failure(self):
        with mock.patch.object(steamui, "_discover") as discover:
            # Mocked bound callbacks retain the timer owner; release them on its thread.
            self.addCleanup(discover.reset_mock)
            ui = steamui.SteamUi()
            self.addCleanup(delete_qobject, ui)
            for _ in range(12):
                ui._tick()
            self.assertEqual(discover.call_count, 1)
            discover.call_args.args[1](None)
            for _ in range(4):
                ui._tick()
            self.assertEqual(discover.call_count, 2)

    def test_big_picture_is_found_under_the_titles_steam_uses(self):
        for t in ("Steam Big Picture Mode", "Big Picture", "Big-Picture-Modus", "Steam-Big-Picture-Modus"):
            self.assertEqual(self.find(["SharedJSContext", t]), "ws://x/1", t)

    def test_other_pages_are_not_taken_for_it_and_the_shared_context_is_found(self):
        self.assertIsNone(self.find(["SharedJSContext", "Steam", "Notifications"]))
        self.assertEqual(self.find(["Big Picture Mode", "SharedJSContext"], shared=True), "ws://x/1")


class Socket(steamui.QObject):
    connected = steamui.Signal()
    disconnected = steamui.Signal()
    textMessageReceived = steamui.Signal(str)
    errorOccurred = steamui.Signal()

    def __init__(self):
        super().__init__()
        self.opened, self.sent = [], []

    def open(self, url):
        self.opened.append(url.toString())

    def sendTextMessage(self, text):
        self.sent.append(json.loads(text))

    def abort(self):
        pass


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.socket = Socket()
        self.discovered, self.completed = [], []
        self.enterContext(mock.patch.object(steamui, 'QWebSocket', return_value=self.socket))
        self.enterContext(mock.patch.object(steamui, '_discover', side_effect=lambda shared, done: self.discovered.append(done)))
        self.addCleanup(lambda: self.socket.errorOccurred.emit() if self.socket in steamui._live else None)

    def test_deadline_prevents_send_even_before_timeout_event_is_processed(self):
        clock = [10.0]
        with mock.patch.object(steamui, 'time', SimpleNamespace(monotonic=lambda: clock[0]), create=True):
            steamui.eval_js('danger()', self.completed.append, timeout=100)
            self.discovered[0]('ws://fixture')
            clock[0] = 10.1
            self.socket.connected.emit()
        self.assertEqual(self.socket.sent, [])
        self.assertEqual(self.completed, [None])

    def test_serializing_the_command_cannot_push_send_past_the_deadline(self):
        clock = [10.0]
        dumps = json.dumps

        def serialize(value):
            clock[0] = 10.101
            return dumps(value)

        with mock.patch.object(steamui, 'time', SimpleNamespace(monotonic=lambda: clock[0])):
            steamui.eval_js('1', self.completed.append, timeout=100)
            self.discovered[0]('ws://fixture')
            with mock.patch.object(steamui.json, 'dumps', side_effect=serialize):
                self.socket.connected.emit()
        self.assertEqual(self.socket.sent, [])
        self.assertEqual(self.completed, [None])

    def test_timeout_finishes_once_and_late_discovery_cannot_open_socket(self):
        from tests.common import wait_for
        steamui.eval_js('1', self.completed.append, timeout=1)
        wait_for(lambda: bool(self.completed))
        self.discovered[0]('ws://fixture')
        self.assertEqual(self.socket.opened, [])
        self.assertEqual(self.completed, [None])

    def test_validity_is_checked_at_send_and_completion_is_once(self):
        steamui.eval_js('1', self.completed.append, valid=lambda: False)
        self.discovered[0]('ws://fixture')
        self.socket.connected.emit()
        self.socket.errorOccurred.emit()
        self.assertEqual(self.socket.sent, [])
        self.assertEqual(self.completed, [None])

    def test_awaited_result_is_delivered_once(self):
        steamui.eval_js('1', self.completed.append)
        self.discovered[0]('ws://fixture')
        self.socket.connected.emit()
        self.assertTrue(self.socket.sent[0]['params']['awaitPromise'])
        self.socket.textMessageReceived.emit(json.dumps({'id': 7, 'result': {'result': {'value': 123}}}))
        self.socket.errorOccurred.emit()
        self.assertEqual(self.completed, [123])

    def test_matching_reply_with_null_result_settles_the_evaluation(self):
        steamui.eval_js('1', self.completed.append)
        self.discovered[0]('ws://fixture')
        self.socket.connected.emit()
        self.socket.textMessageReceived.emit(json.dumps({'id': 8, 'result': None}))
        self.assertEqual(self.completed, [])
        self.socket.textMessageReceived.emit(json.dumps({'id': 7, 'result': None}))
        self.assertEqual(self.completed, [None])
        self.assertNotIn(self.socket, steamui._live)


class Discovery(unittest.TestCase):
    class Reply(steamui.QObject):
        readyRead = steamui.Signal()
        finished = steamui.Signal()
        def __init__(self, data):
            super().__init__()
            self.data, self.aborted = data, False
        def setReadBufferSize(self, size):
            self.limit = size
        def bytesAvailable(self):
            return len(self.data)
        def readAll(self):
            return self.data
        def error(self):
            return (steamui.QNetworkReply.NetworkError.OperationCanceledError if self.aborted
                    else steamui.QNetworkReply.NetworkError.NoError)
        def abort(self):
            self.aborted = True
            self.finished.emit()

    def test_page_list_is_shared_and_malformed_or_oversized_lists_fail_closed(self):
        fixtures = [(json.dumps(pages('SharedJSContext', 'Big Picture')).encode(), ['ws://x/0', 'ws://x/1']),
                    (b'{bad', [None, None]), (b'x' * (256 * 1024 + 1), [None, None])]
        for data, expected in fixtures:
            with self.subTest(size=len(data)):
                reply = self.Reply(data)
                manager = mock.Mock()
                manager.get.return_value = reply
                with mock.patch.object(steamui, 'QNetworkAccessManager', return_value=manager):
                    discovery = steamui._Discovery(None)
                results = []
                discovery.request(True, results.append)
                discovery.request(False, results.append)
                self.assertEqual(results, [])
                self.assertEqual(manager.get.call_count, 1)
                reply.readyRead.emit()
                if not reply.aborted:
                    reply.finished.emit()
                self.assertEqual(results, expected)
                delete_qobject(discovery)

    def test_excessive_json_nesting_releases_waiters_and_allows_a_retry(self):
        depth = 20_000  # exceeds the decoder's nesting limit while staying inside the reply size limit
        invalid = self.Reply(b'[' * depth + b']' * depth)
        valid = self.Reply(json.dumps(pages('SharedJSContext')).encode())
        manager = mock.Mock()
        manager.get.side_effect = [invalid, valid]
        with mock.patch.object(steamui, 'QNetworkAccessManager', return_value=manager):
            discovery = steamui._Discovery(None)
        self.addCleanup(delete_qobject, discovery)
        results = []

        def launch_done(url):
            results.append(('launch', url))
            discovery.request(True, lambda retry_url: results.append(('retry', retry_url)))

        discovery.request(True, launch_done)
        discovery.request(False, lambda url: results.append(('focus', url)))
        invalid.finished.emit()
        self.assertEqual(results, [('launch', None), ('focus', None)])

        valid.finished.emit()
        self.assertEqual(results, [('launch', None), ('focus', None), ('retry', 'ws://x/0')])

    def test_deleting_the_focus_observer_does_not_block_other_discovery_waiters(self):
        reply = self.Reply(json.dumps(pages('Big Picture', 'SharedJSContext')).encode())
        manager = mock.Mock()
        manager.get.return_value = reply
        with mock.patch.object(steamui, 'QNetworkAccessManager', return_value=manager):
            discovery = steamui._Discovery(None)
        self.addCleanup(delete_qobject, discovery)
        results = []
        with mock.patch.object(steamui, '_discover', discovery.request):
            ui = steamui.SteamUi()
            for _ in range(4):
                ui._tick()
        discovery.request(True, results.append)
        manager.get.assert_called_once()
        delete_qobject(ui)
        reply.finished.emit()
        self.assertEqual(results, ['ws://x/1'])

    def test_disconnected_focus_does_not_accept_the_old_connection_reply(self):
        from tests.common import delete_qobject
        ui = steamui.SteamUi()
        ui._request_id = 5
        ui._set((123, 'Old'))
        ui._disconnected()
        ui._reply(json.dumps({'id': 5, 'result': {'result': {'value': json.dumps({'appid': 123})}}}))
        self.assertEqual(ui._last, (0, ''))
        delete_qobject(ui)

if __name__ == "__main__":
    unittest.main()
