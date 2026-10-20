#!/usr/bin/env python3
"""
Builds a tiny fake podcast to try the script on without Premiere:
two mic tracks (host + guest), a video track, two clips per track, a transcript.

    python3 tests/make_fixture.py ~/Desktop/demo
    python3 skills/podcast-cleanup/scripts/podcast_clean.py --xml ~/Desktop/demo/demo.xml --transcript ~/Desktop/demo/demo.json

Timeline (seconds):
  1.0-3.0   host: "so welcome to the show"
  3.0-5.5   2.5 s of silence                      -> shortened
  5.5-7.8   guest: "thanks [um] for having me"     -> the um has silence on both sides: cut
  8.5-9.4   guest: "it's[um]great"                 -> um glued to the words: left in, marker
  9.4-12.0  silence with a laugh nobody transcribed at 10.5-10.9 -> laugh kept, air around it shortened
  12.0-14.8 host: "right ... uh ...... okay"       -> uh cut, long pause shortened
"""
import json
import math
import os
import random
import struct
import subprocess
import sys
import wave

SR = 48000
DUR = 20.0
FPS = 30

HOST = [("so", 1.0, 1.3), ("welcome", 1.35, 1.8), ("to", 2.2, 2.35), ("the", 2.4, 2.5), ("show.", 2.55, 3.0),
        ("right.", 12.0, 12.3), ("", 12.6, 12.9, "uh"), ("okay.", 14.4, 14.8)]
GUEST = [("thanks", 5.5, 5.9), ("", 6.2, 6.6, "um"), ("for", 6.9, 7.1), ("having", 7.15, 7.5), ("me.", 7.55, 7.8),
         ("it's", 8.5, 8.7), ("", 8.7, 9.0, "um"), ("great.", 9.0, 9.4)]
LAUGH = (10.5, 10.9)   # guest track, not in the transcript


def tone(buf, t0, t1, freq, level_db):
    a = 32767 * (10 ** (level_db / 20))
    for i in range(int(t0 * SR), int(t1 * SR)):
        env = min(1.0, (i - t0 * SR) / 240.0, (t1 * SR - i) / 240.0)   # 5 ms ramps
        buf[i] += a * env * math.sin(2 * math.pi * freq * i / SR) * (0.8 + 0.2 * math.sin(i / 300.0))


def write_wav(path, words, extra=()):
    rnd = random.Random(7)
    buf = [rnd.uniform(-1, 1) * 32767 * 10 ** (-62 / 20) for _ in range(int(DUR * SR))]   # room tone
    for w in words:
        tone(buf, w[1], w[2], 180 if w[0] else 140, -12 if w[0] else -16)
    for t0, t1 in extra:
        tone(buf, t0, t1, 260, -14)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, int(s)))) for s in buf))


def transcript(path):
    segs = []
    for spk, ws in (("host", HOST), ("guest", GUEST)):
        for w in ws:
            word = {"text": w[0], "start": w[1], "duration": round(w[2] - w[1], 3),
                    "eos": w[0].endswith("."), "confidence": 1, "type": "word"}
            if not w[0]:
                word["tags"] = ["disfluency"]
            segs.append({"start": w[1], "duration": word["duration"], "speaker": spk, "words": [word]})
    segs.sort(key=lambda s: s["start"])
    json.dump({"language": "en-us", "speakers": [{"id": "host", "name": "Host"}, {"id": "guest", "name": "Guest"}],
               "segments": segs}, open(path, "w"), indent=1)


def rate():
    return "<rate><timebase>%d</timebase><ntsc>FALSE</ntsc></rate>" % FPS


def clip(cid, name, fid, path, start, end, kind, links, full):
    tpf = 254016000000 // FPS
    fdef = '<file id="%s"/>' % fid
    if full:
        media = ("<video><samplecharacteristics>%s<width>320</width><height>180</height></samplecharacteristics></video>" % rate()
                 if kind == "video" else
                 "<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics><channelcount>1</channelcount></audio>")
        fdef = ('<file id="%s"><name>%s</name><pathurl>file://%s</pathurl>%s<duration>%d</duration><media>%s</media></file>'
                % (fid, name, path, rate(), int(DUR * FPS), media))
    lk = "".join("<link><linkclipref>%s</linkclipref><mediatype>%s</mediatype><trackindex>%d</trackindex><clipindex>%d</clipindex>%s</link>"
                 % (r, m, ti, ci, "<groupindex>1</groupindex>" if m == "audio" else "") for r, m, ti, ci in links)
    st = "<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>" if kind == "audio" else ""
    return ('<clipitem id="%s"><masterclipid>m-%s</masterclipid><name>%s</name><enabled>TRUE</enabled><duration>%d</duration>%s'
            '<start>%d</start><end>%d</end><in>%d</in><out>%d</out><pproTicksIn>%d</pproTicksIn><pproTicksOut>%d</pproTicksOut>%s%s%s</clipitem>'
            % (cid, fid, name, int(DUR * FPS), rate(), start, end, start, end, start * tpf, end * tpf, fdef, st, lk))


def sequence(path, video, host, guest):
    half = int(10 * FPS)
    full = int(DUR * FPS)
    v, a1, a2 = [], [], []
    for k, (s, e) in enumerate(((0, half), (half, full)), 1):
        ids = ("v%d" % k, "h%d" % k, "g%d" % k)
        links = [(ids[0], "video", 1, k), (ids[1], "audio", 1, k), (ids[2], "audio", 2, k)]
        v.append(clip(ids[0], "camera.mp4", "f-video", video, s, e, "video", links, k == 1))
        a1.append(clip(ids[1], "host.wav", "f-host", host, s, e, "audio", links, k == 1))
        a2.append(clip(ids[2], "guest.wav", "f-guest", guest, s, e, "audio", links, k == 1))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="sequence-1">'
           '<uuid>00000000-0000-0000-0000-000000000001</uuid><duration>%d</duration>%s<name>Demo episode</name><media>'
           '<video><format><samplecharacteristics>%s<width>320</width><height>180</height></samplecharacteristics></format>'
           '<track>%s</track></video><audio><track>%s</track><track>%s</track></audio></media>'
           '<timecode>%s<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
           '</sequence></xmeml>\n' % (full, rate(), rate(), "".join(v), "".join(a1), "".join(a2), rate()))
    open(path, "w").write(xml)


def build(out_dir):
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    host, guest = os.path.join(out_dir, "host.wav"), os.path.join(out_dir, "guest.wav")
    video = os.path.join(out_dir, "camera.mp4")
    write_wav(host, HOST)
    write_wav(guest, GUEST, [LAUGH])
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=0x223344:s=320x180:r=%d:d=%d" % (FPS, DUR), "-pix_fmt", "yuv420p", video], check=True)
    transcript(os.path.join(out_dir, "demo.json"))
    sequence(os.path.join(out_dir, "demo.xml"), video, host, guest)
    return out_dir


if __name__ == "__main__":
    d = build(sys.argv[1] if len(sys.argv) > 1 else "demo")
    print("Demo podcast written to %s (demo.xml + demo.json + media)" % d)
