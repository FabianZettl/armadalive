import unittest

from armadalive import lupe

STATUS = """PipeWire 'pipewire-0' [1.6.4, armada@armada, cookie:1]
 └─ Clients:
        33. wireplumber                         [1.6.4, armada@armada, pid:2036]

Audio
 ├─ Devices:
 │      50. Built-in Audio                      [alsa]
 ├─ Sinks:
 │  *   65. Built-in Audio Headphones Playback  [vol: 1.00]
 └─ Streams:

Video
 ├─ Devices:
 │      47. Iris Decoder                        [v4l2]
 │      48. Iris Encoder                        [v4l2]
 │  
 ├─ Sinks:
 │  
 ├─ Sources:
 │  *   62. (null)                             
 │      74. (null)                             
 │  
 ├─ Filters:
 │  
 └─ Streams:

Settings
 └─ Default Configured Devices:
"""


class Lupe(unittest.TestCase):
    def test_video_sources_are_read_from_wpctl_status(self):
        self.assertEqual(lupe.video_sources(STATUS), [62, 74])
        self.assertEqual(lupe.video_sources("Audio\n ├─ Sources:\n │  *   9. mic\n"), [])
        self.assertEqual(lupe.video_sources(""), [])

    def test_a_value_is_read_from_wpctl_inspect(self):
        text = 'id 62, type PipeWire:Interface:Node\n  * client.id = "61"\n    media.name = "gamescope"\n  * object.serial = "62"\n'
        self.assertEqual(lupe.inspected(text, "client.id"), "61")
        self.assertEqual(lupe.inspected(text, "media.name"), "gamescope")
        self.assertEqual(lupe.inspected(text, "missing"), "")

    def test_the_region_becomes_pixels_to_cut_off(self):
        self.assertEqual(lupe.crop((0, 0, 1, 1), (1920, 1080)), (0, 0, 0, 0))
        self.assertEqual(lupe.crop((0.75, 0.5, 0.25, 0.5), (1920, 1080)), (1440, 540, 0, 0))
        self.assertEqual(lupe.crop((0.1, 0.1, 0.5, 0.5), (1000, 1000)), (100, 100, 400, 400))
        left, top, right, bottom = lupe.crop((0.9, 0.9, 0.5, 0.5), (1000, 1000))   # runs past the edge: clipped
        self.assertEqual((left, top, right, bottom), (900, 900, 0, 0))

    def test_the_output_fits_the_box_and_stays_even(self):
        w, h = lupe.fit(16 / 9, 600, 1000)
        self.assertEqual((w, h), (600, 337 // 2 * 2))
        w, h = lupe.fit(1.0, 600, 400)     # the box is the limit
        self.assertEqual((w, h), (400, 400))
        w, h = lupe.fit(2.0, 5000, 5000)   # never beyond MAX_SIDE
        self.assertLessEqual(max(w, h), lupe.MAX_SIDE)
        self.assertTrue(w % 2 == 0 and h % 2 == 0)

    def test_the_pipeline_crops_before_it_scales(self):
        args = lupe.pipeline(62, (1920, 1080), (0.5, 0, 0.5, 0.5), (640, 360), 30)
        text = " ".join(args)
        self.assertIn("path=62", text)
        self.assertIn("left=960 top=0 right=0 bottom=540", text)
        self.assertLess(text.index("videocrop"), text.index("videoscale"))
        self.assertIn("width=640,height=360", text)

    def test_frames_are_cut_from_a_stream_in_odd_pieces(self):
        f = lupe.Frames(8)
        self.assertEqual(f.feed(b"abc"), [])
        self.assertEqual(f.feed(b"defghijkl"), [b"abcdefgh"])
        self.assertEqual(f.feed(b"mnopqrstuvwx"), [b"ijklmnop", b"qrstuvwx"])


if __name__ == "__main__":
    unittest.main()
