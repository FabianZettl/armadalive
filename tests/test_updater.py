import hashlib, io, json, os, tempfile, unittest

from tests.common import app  # noqa: F401
from armadalive import updater


class Version(unittest.TestCase):
    def test_comparison(self):
        self.assertGreater(updater._version("v0.10.0"), updater._version("0.9.9"))
        self.assertEqual(updater._version("v1.2.3"), updater._version("1.2.3"))

    def test_sha256(self):
        f = os.path.join(tempfile.mkdtemp(), "x")
        with open(f, "wb") as out:
            out.write(b"abc")
        self.assertEqual(updater.sha256(f), hashlib.sha256(b"abc").hexdigest())


class Check(unittest.TestCase):
    def check(self, release):
        updater.REPO_ID = "o/r"
        updater._get = lambda url, timeout=15: io.BytesIO(json.dumps(release).encode())
        u = updater.Updater()
        u._check()
        return u.state

    def test_a_newer_release_with_a_checksum_is_offered(self):
        s = self.check({"tag_name": "v99.0.0", "assets": [
            {"name": updater.ASSET, "browser_download_url": "https://x/a"}, {"name": updater.CHECKSUM, "browser_download_url": "https://x/s"}]})
        self.assertEqual((s["status"], s["latest"]), ("available", "v99.0.0"))

    def test_a_newer_release_without_a_checksum_is_refused(self):
        s = self.check({"tag_name": "v99.0.0", "assets": [{"name": updater.ASSET, "browser_download_url": "https://x/a"}]})
        self.assertEqual(s["status"], "error")
        self.assertIn("checksum", s["message"])

    def test_the_same_version_is_up_to_date(self):
        self.assertEqual(self.check({"tag_name": "v0.0.1", "assets": []})["status"], "uptodate")


if __name__ == "__main__":
    unittest.main()
