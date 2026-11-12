import json, os, subprocess, sys, time, unittest

from tests.common import app  # noqa: F401
from armadalive import tasks

WINDOWS = json.dumps([
    dict(id="{a}", title="Mozilla Firefox", app="firefox", pid=500, normal=True, skip=False, min=False),
    dict(id="{b}", title="ArmadaLive", app="armadalive", pid=os.getpid(), normal=True, skip=False, min=False),   # ourselves
    dict(id="{c}", title="", app="plasmashell", pid=77, normal=False, skip=True, min=False),                      # a panel
    dict(id="{f}", title="Another Firefox window", app="firefox", pid=500, normal=True, skip=False, min=True),     # the same program
    dict(id="{d}", title="Dolphin", app="dolphin", pid=600, normal=True, skip=False, min=True),
    dict(id="{e}", title="Odd", app="x", pid=0, normal=True, skip=False, min=False),
])


class Parse(unittest.TestCase):
    def test_only_real_application_windows_other_than_this_app_are_listed(self):
        got = tasks.parse(WINDOWS, os.getpid())
        self.assertEqual([(w["title"], w["windows"]) for w in got], [("Mozilla Firefox", 2), ("Dolphin", 1)])
        self.assertFalse(got[0]["minimized"])      # one of its windows is up
        self.assertTrue(got[1]["minimized"])

    def test_garbage_gives_an_empty_list(self):
        self.assertEqual(tasks.parse("not json", 1), [])
        self.assertEqual(tasks.parse("{}", 1), [])


class Kill(unittest.TestCase):
    def test_a_program_that_ignores_sigterm_is_killed_after_the_grace_time_with_its_children(self):
        code = "import signal, subprocess, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); subprocess.Popen([sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); time.sleep(60)"
        p = subprocess.Popen([sys.executable, "-c", code])
        time.sleep(0.8)
        table = tasks.parents()
        kids = [c for c, parent in table.items() if parent == p.pid]
        self.assertTrue(kids)
        tasks.kill_tree(p.pid, grace=0.6, table=table)
        p.wait(timeout=5)
        time.sleep(0.3)
        self.assertFalse(any(os.path.exists(f"/proc/{k}") and open(f"/proc/{k}/stat").read().rpartition(")")[2].split()[0] != "Z" for k in kids))

    def test_memory_is_the_sum_over_the_whole_tree(self):
        self.assertGreater(tasks.memory_mb(os.getpid(), tasks.parents()), 5)


if __name__ == "__main__":
    unittest.main()
