import struct, unittest
from unittest import mock

from tests.common import app  # noqa: F401

from armadalive import trackpad as tp


class Fake:
    def __init__(self):
        self.events = []

    def emit(self, kind, code, value):
        self.events.append((kind, code, value))

    def sync(self):
        self.events.append("sync")


class Effect(unittest.TestCase):
    def test_a_rumble_effect_is_the_48_bytes_the_kernel_expects(self):
        buf = tp.rumble_effect(0x7000, 25)
        self.assertEqual(len(buf), 48)
        kind, ident, _direction, _button, _interval, length, _delay = struct.unpack_from("<HhHHHHH", buf)
        self.assertEqual((kind, ident, length), (tp.FF_RUMBLE, -1, 25))
        self.assertEqual(struct.unpack_from("<HH", buf, 16), (0x7000, 0))

    def test_a_constant_effect_is_48_bytes_too(self):
        buf = tp.constant_effect(35, 4)
        self.assertEqual(len(buf), 48)
        self.assertEqual(struct.unpack_from("<HhHHHHH", buf)[0::5], (tp.FF_CONSTANT, 35))
        self.assertEqual(struct.unpack_from("<h", buf, 16)[0], 0x6000)

    def test_the_haptic_motor_is_found_by_name(self):
        text = 'I: Bus=0000\nN: Name="gpio-keys"\nH: Handlers=event2\n\nN: Name="qcom-hv-haptics"\nH: Handlers=event8 \n'
        with mock.patch("builtins.open", mock.mock_open(read_data=text)):
            self.assertEqual(tp.haptics_node(), "/dev/input/event8")


class Moves(unittest.TestCase):
    def setUp(self):
        self.t = tp.Trackpad()
        self.mouse, self.back = Fake(), Fake()
        self.keys = Fake()
        self.t._mouse, self.t._back, self.t._keys = self.mouse, self.back, self.keys

    def test_small_movements_add_up_instead_of_getting_lost(self):
        for _ in range(10):
            self.t.move(0.2, 0)    # 0.36 of a step each: three of them make one
        steps = sum(v for e in self.mouse.events if e != "sync" for k, c, v in [e] if c == tp.REL_X)
        self.assertEqual(steps, int(10 * 0.2 * tp.SENSITIVITY))

    def test_a_tap_is_a_press_and_a_release_of_that_button(self):
        self.t.button("right", True)
        self.t.button("right", False)
        self.assertEqual([e for e in self.mouse.events if e != "sync"],
                         [(tp.EV_KEY, tp.BTN_RIGHT, 1), (tp.EV_KEY, tp.BTN_RIGHT, 0)])

    def test_back_buttons_go_to_the_pad_not_the_mouse(self):
        self.t.button("R5", True)
        self.assertEqual([e for e in self.back.events if e != "sync"], [(tp.EV_KEY, tp.BTN_TRIGGER_HAPPY1 + 3, 1)])
        self.assertEqual(self.mouse.events, [])

    def test_a_key_is_a_tap_of_that_key(self):
        self.t.press("esc")
        self.assertEqual([e for e in self.keys.events if e != "sync"], [(tp.EV_KEY, 1, 1), (tp.EV_KEY, 1, 0)])
        self.t.press("nonsense")
        self.assertEqual(len(self.keys.events), 4)

    def test_a_flick_glides_on_and_slows_down_to_a_stop(self):
        t = self.t
        t.nudge = lambda: self.ticks.append(1)
        self.ticks = []
        t.fling(1200, 0)
        steps = 0
        while t._glide and steps < 400:
            t._step()
            steps += 1
        moved = sum(v for e in self.mouse.events if e != "sync" for k, c, v in [e] if c == tp.REL_X)
        self.assertGreater(moved, 100)                 # it carried on after the finger left
        self.assertLess(steps, 400)                    # and came to rest
        self.assertGreaterEqual(len(self.ticks), 2)    # with the ticks of a ball's friction
        t._frame.stop()

    def test_a_slow_lift_does_not_glide_and_the_switch_turns_it_off(self):
        t = self.t
        t.fling(100, 0)
        self.assertIsNone(t._glide)
        t.setTrackball(False)
        t.fling(1200, 0)
        self.assertIsNone(t._glide)
        t.setTrackball(True)
        t.fling(1200, 0)
        t.stopGlide()
        self.assertIsNone(t._glide)
        t._frame.stop()

    def test_an_unknown_button_does_nothing(self):
        self.t.button("L9", True)
        self.assertEqual(self.mouse.events + self.back.events, [])

    def test_ticks_come_no_faster_than_every_25_ms_and_a_click_always_does(self):
        t = self.t
        played = []
        t._motors[0].play = lambda ms, fade: played.append(ms)
        t.nudge(); t.nudge(); t.nudge()
        self.assertEqual(played, [12])            # one tick, the others came too soon
        t.tick()                                  # a click is never held back
        self.assertEqual(played, [12, 40])
        t._release.stop()

    def test_a_motor_that_fails_does_not_crash_the_buzz(self):
        t = self.t
        def broken(ms, fade): raise OSError(28, "no space")
        t._motors[0].play = broken
        t.tick()                                  # no exception
        t._release.stop()

    def test_no_uinput_means_a_message_and_no_crash(self):
        t = tp.Trackpad()
        with mock.patch.object(tp.os, "open", side_effect=PermissionError(13, "Permission denied")):
            t.move(5, 5)
        self.assertIn("uinput", t.error)


if __name__ == "__main__":
    unittest.main()
