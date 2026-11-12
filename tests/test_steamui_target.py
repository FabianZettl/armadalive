import io, json, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import steamui


def pages(*titles):
    return io.BytesIO(json.dumps([dict(type="page", title=t, webSocketDebuggerUrl=f"ws://x/{i}") for i, t in enumerate(titles)]).encode())


class Target(unittest.TestCase):
    def find(self, titles, shared=False):
        with mock.patch("urllib.request.urlopen", lambda *a, **k: pages(*titles)):
            return steamui._target(shared)

    def test_big_picture_is_found_under_the_titles_steam_uses(self):
        for t in ("Steam Big Picture Mode", "Big Picture", "Big-Picture-Modus", "Steam-Big-Picture-Modus"):
            self.assertEqual(self.find(["SharedJSContext", t]), "ws://x/1", t)

    def test_other_pages_are_not_taken_for_it_and_the_shared_context_is_found(self):
        self.assertIsNone(self.find(["SharedJSContext", "Steam", "Notifications"]))
        self.assertEqual(self.find(["Big Picture Mode", "SharedJSContext"], shared=True), "ws://x/1")


if __name__ == "__main__":
    unittest.main()
