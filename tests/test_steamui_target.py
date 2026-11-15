import json, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import steamui


def pages(*titles):
    return [dict(type="page", title=t, webSocketDebuggerUrl=f"ws://x/{i}") for i, t in enumerate(titles)]


class Target(unittest.TestCase):
    def find(self, titles, shared=False):
        return steamui._target(pages(*titles), shared)

    def test_discovery_is_requested_without_reading_the_socket_on_the_owner_thread(self):
        fetch = mock.patch("urllib.request.urlopen", side_effect=AssertionError("synchronous discovery"))
        with fetch as open_url:
            ui = steamui.SteamUi()
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


if __name__ == "__main__":
    unittest.main()
