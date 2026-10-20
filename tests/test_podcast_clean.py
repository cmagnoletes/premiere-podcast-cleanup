"""Run with:  python3 -m unittest discover tests   (needs ffmpeg)"""
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "podcast-cleanup", "scripts"))
sys.path.insert(0, HERE)
import make_fixture  # noqa: E402
import podcast_clean  # noqa: E402

FPS = 30


class DemoPodcast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="podcast-clean-")
        make_fixture.build(cls.dir)
        cls.xml = os.path.join(cls.dir, "demo.xml")
        cls.json = os.path.join(cls.dir, "demo.json")
        cls.out = os.path.join(cls.dir, "out.xml")
        cls.rc = podcast_clean.main(["--xml", cls.xml, "--transcript", cls.json, "--out", cls.out])
        cls.edits = json.load(open(os.path.join(cls.dir, "out-edits.json")))["edits"]
        cls.seq = ET.parse(cls.out).getroot().find("sequence")

    def kinds(self, kind):
        return [e for e in self.edits if e["kind"] == kind]

    def secs(self, e):
        return e["f0"] / FPS, e["f1"] / FPS

    def test_self_check_passes(self):
        self.assertEqual(self.rc, 0)

    def test_long_pause_is_shortened_not_removed(self):
        p = [e for e in self.kinds("pause") if 3.0 <= self.secs(e)[0] < 5.5]
        self.assertEqual(len(p), 1)
        a, b = self.secs(p[0])
        self.assertAlmostEqual(a - 3.0, 0.35 + 0.04, delta=0.07)   # air kept after "show."
        self.assertAlmostEqual(5.5 - b, 0.25 + 0.04, delta=0.07)   # air kept before "thanks"

    def test_um_with_silence_around_it_is_cut(self):
        f = [e for e in self.kinds("filler") if 5.9 <= self.secs(e)[0] < 6.9]
        self.assertEqual(len(f), 1)
        a, b = self.secs(f[0])
        self.assertLessEqual(a, 6.2)
        self.assertGreaterEqual(b, 6.6)

    def test_um_glued_to_words_is_left_in_with_a_marker(self):
        c = [e for e in self.kinds("check") if 8.6 <= self.secs(e)[0] < 9.1]
        self.assertEqual(len(c), 1)
        self.assertFalse(any(self.secs(e)[0] < 9.0 and self.secs(e)[1] > 8.7 for e in self.edits if e["kind"] != "check"))
        self.assertEqual(len(self.seq.findall("marker")), 1)

    def test_untranscribed_laugh_survives(self):
        for e in self.edits:
            if e["kind"] == "check":
                continue
            a, b = self.secs(e)
            self.assertFalse(a < 10.9 and b > 10.5, "a cut touched the laugh")

    def test_uh_inside_long_pause_is_cut_and_pause_shortened(self):
        f = [e for e in self.kinds("filler") if 12.3 <= self.secs(e)[0] < 14.4]
        self.assertEqual(len(f), 1)
        a, b = self.secs(f[0])
        self.assertLessEqual(a, 12.6)
        self.assertGreaterEqual(b, 12.9)
        self.assertGreater(b - a, 1.0)

    def test_no_cut_touches_a_word(self):
        words = [w for w in podcast_clean.load_transcript(self.json) if not w["filler"]]
        for e in self.edits:
            a, b = self.secs(e)
            for w in words:
                self.assertFalse(w["start"] < b and w["end"] > a, "cut %s-%s hits %r" % (a, b, w["text"]))

    def test_every_track_cut_identically_and_contiguous(self):
        tracks = []
        for kind in ("video", "audio"):
            for t in self.seq.find("media").find(kind).findall("track"):
                tracks.append([(int(c.findtext("start")), int(c.findtext("end")), int(c.findtext("in"))) for c in t.findall("clipitem")])
        self.assertEqual(len(tracks), 3)
        self.assertEqual(tracks[0], tracks[1])
        self.assertEqual(tracks[0], tracks[2])
        for (s1, e1, _), (s2, _, _) in zip(tracks[0], tracks[0][1:]):
            self.assertEqual(e1, s2, "gap or overlap on the timeline")
        removed = sum(e["f1"] - e["f0"] for e in self.edits)
        self.assertEqual(tracks[0][-1][1], 600 - removed)
        self.assertEqual(int(self.seq.findtext("duration")), 600 - removed)

    def test_ticks_match_frames(self):
        for c in self.seq.iter("clipitem"):
            self.assertEqual(int(c.findtext("pproTicksIn")), int(c.findtext("in")) * (254016000000 // FPS))
            self.assertEqual(int(c.findtext("pproTicksOut")), int(c.findtext("out")) * (254016000000 // FPS))

    def test_links_point_to_existing_pieces(self):
        ids = {c.get("id") for c in self.seq.iter("clipitem")}
        for c in self.seq.iter("clipitem"):
            for ln in c.findall("link"):
                self.assertIn(ln.findtext("linkclipref"), ids)

    def test_file_defined_once_then_referenced(self):
        full = [f for f in self.seq.iter("file") if len(f)]
        self.assertEqual(sorted(f.get("id") for f in full), ["f-guest", "f-host", "f-video"])

    def test_fillers_only_mode_leaves_pauses(self):
        out = os.path.join(self.dir, "fillers.xml")
        podcast_clean.main(["--xml", self.xml, "--transcript", self.json, "--out", out, "--mode", "fillers"])
        edits = json.load(open(os.path.join(self.dir, "fillers-edits.json")))["edits"]
        self.assertFalse([e for e in edits if e["kind"] == "pause"])
        self.assertEqual(len([e for e in edits if e["kind"] == "filler"]), 2)

    def test_transcript_from_another_sequence_is_refused(self):
        bad = os.path.join(self.dir, "bad.json")
        data = json.load(open(self.json))
        data["segments"].append({"start": 90, "duration": 1, "words": [{"text": "late", "start": 90, "duration": 0.5}]})
        json.dump(data, open(bad, "w"))
        with self.assertRaises(SystemExit):
            podcast_clean.main(["--xml", self.xml, "--transcript", bad, "--out", os.path.join(self.dir, "bad.xml")])


class Paths(unittest.TestCase):
    def test_media_paths_from_premiere_xml(self):
        f = podcast_clean.path_from_url
        self.assertEqual(f("file://localhost/Volumes/Media/ep%2001.wav"), "/Volumes/Media/ep 01.wav")
        self.assertEqual(f("file://localhost/C%3a/Users/Joe/Podcast/ep1.wav"), "C:/Users/Joe/Podcast/ep1.wav")
        self.assertEqual(f("file:///D:/Podcast/cam%20a.mp4"), "D:/Podcast/cam a.mp4")
        self.assertEqual(f("file://NAS/share/ep1.wav"), "//NAS/share/ep1.wav")


if __name__ == "__main__":
    unittest.main()
