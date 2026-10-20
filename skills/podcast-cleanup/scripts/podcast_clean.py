#!/usr/bin/env python3
"""
podcast_clean.py: remove ums, uhs and long pauses from a Premiere Pro sequence.

Inputs (all in the SAME sequence's timeline time):
  --xml         the sequence, exported from Premiere as Final Cut Pro XML
  --transcript  the sequence's transcript, exported from Premiere's Text panel as JSON
  --audio       optional: a WAV/any-audio mixdown of the sequence. When omitted, the script
                reads the audio straight from the media files the XML points to.

Output:
  a new FCP XML (import it into Premiere: a new sequence appears, your original is untouched),
  an HTML report listing every edit with its timecode and the words around it,
  a JSON file with the same edits (and the spots left for you to check, as markers).

How it decides (the safety rules):
  1. A cut never touches a transcribed word (except the filler itself).
  2. A cut never touches a sound the transcript does not explain (laughter, a cough,
     crosstalk the transcript missed): loud + unexplained = protected.
  3. A filler is cut only if there is silence on BOTH sides of it. An "um" that runs straight
     into a word is left in place and listed as a marker for you to check by ear.
  4. A pause longer than --max-pause is shortened, keeping --keep-after seconds after the
     last word and --keep-before seconds before the next one. Nothing is sped up or
     re-encoded: whole frames are removed and every track is cut at the same moment,
     so cameras and mics stay in sync.

Standard library only. Needs ffmpeg on PATH. Python 3.9+.
"""
import argparse
import array
import copy
import html
import json
import math
import os
import re
import statistics
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from fractions import Fraction
from typing import NoReturn
from urllib.parse import unquote, urlparse

VERSION = "1.0.0"
WIN = 0.01                     # analysis window, seconds (10 ms)
SR = 16000                     # analysis sample rate
SPW = int(SR * WIN)            # samples per window
TICKS_PER_SEC = 254016000000   # Premiere's internal time unit
FILLER_WORDS = {"um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm", "er", "erm", "ah", "ahh",
                "hmm", "hm", "mm", "mmm"}
LEXICAL_WATCH = {"like", "you know", "i mean", "kind of", "sort of", "basically", "actually"}


# --------------------------------------------------------------------------- helpers

def die(msg) -> NoReturn:
    sys.stderr.write("\nERROR: " + msg + "\n")
    sys.exit(2)


def warn(msg, warnings):
    warnings.append(msg)
    sys.stderr.write("warning: " + msg + "\n")


def db(amp):
    return 20 * math.log10(max(amp, 1) / 32768.0)


def amp(dbfs):
    return 32768.0 * (10 ** (dbfs / 20.0))


def norm_word(t):
    return re.sub(r"[^a-z' ]", "", (t or "").lower()).strip()


def rate_of(el):
    """Frames per second (exact Fraction) of an element that has a <rate> child."""
    r = el.find("rate")
    if r is None:
        return None
    tb = int(r.findtext("timebase", "30"))
    ntsc = (r.findtext("ntsc", "FALSE") or "").strip().upper() == "TRUE"
    return Fraction(tb * 1000, 1001) if ntsc else Fraction(tb)


def ticks_per_frame(fps):
    return int(round(Fraction(TICKS_PER_SEC) / fps))


def timecode(frame, fps):
    nominal = int(round(float(fps)))
    frame = max(0, int(frame))
    ff = frame % nominal
    s = frame // nominal
    return "%02d:%02d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60, ff)


def path_from_url(url):
    if not url:
        return None
    if url.startswith("file:"):
        p = unquote(urlparse(url).path)
        # file://localhost/Volumes/... and Windows file:///C:/...
        if re.match(r"^/[A-Za-z]:/", p):
            p = p[1:]
        return p
    return unquote(url)


# --------------------------------------------------------------------------- transcript

def load_transcript(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception as e:
        die("could not read the transcript JSON (%s): %s" % (path, e))
    segs = data.get("segments") if isinstance(data, dict) else None
    if not segs:
        die("the transcript has no 'segments'. Export it from Premiere's Text panel as JSON "
            "(Transcript tab > ... menu > Export transcript > JSON).")
    words = []
    for seg in segs:
        for w in seg.get("words", []):
            try:
                st = float(w["start"])
                du = float(w.get("duration", 0.0))
            except (KeyError, TypeError, ValueError):
                continue
            text = (w.get("text") or "").strip()
            tags = w.get("tags") or []
            n = norm_word(text)
            is_filler = (text == "" or "disfluency" in tags or n in FILLER_WORDS)
            words.append({"text": text, "n": n, "start": st, "end": st + max(du, 0.0),
                          "eos": bool(w.get("eos")), "filler": is_filler,
                          "speaker": seg.get("speaker")})
    words.sort(key=lambda x: x["start"])
    if not words:
        die("the transcript has no words with timings.")
    return words


# --------------------------------------------------------------------------- XML

class Seq:
    def __init__(self, path):
        try:
            self.tree = ET.parse(path)
        except ET.ParseError as e:
            die("could not parse the XML (%s). Export it from Premiere with "
                "File > Export > Final Cut Pro XML. Details: %s" % (path, e))
        self.root = self.tree.getroot()
        if self.root.tag != "xmeml":
            die("this is not a Final Cut Pro 7 XML (xmeml) file. In Premiere use "
                "File > Export > Final Cut Pro XML (not FCPXML from Final Cut Pro X).")
        seq = self.root.find("sequence")
        if seq is None:
            seq = next(self.root.iter("sequence"), None)
        if seq is None:
            die("no <sequence> found in the XML.")
        self.seq = seq
        self.fps = rate_of(seq) or Fraction(30)
        self.name = seq.findtext("name", "Sequence")
        self.media = seq.find("media")
        self.tracks = []   # (kind, track element)
        for kind in ("video", "audio"):
            m = self.media.find(kind) if self.media is not None else None
            if m is None:
                continue
            for t in m.findall("track"):
                self.tracks.append((kind, t))
        # file id -> path (first full definition wins)
        self.files = {}
        for f in self.root.iter("file"):
            fid = f.get("id")
            url = f.findtext("pathurl")
            if fid and url and fid not in self.files:
                self.files[fid] = path_from_url(url)

    def duration_frames(self):
        end = 0
        for _, t in self.tracks:
            for it in t:
                if it.tag in ("clipitem", "generatoritem"):
                    e = int(it.findtext("end", "0"))
                    end = max(end, e)
        d = self.seq.findtext("duration")
        return max(end, int(d) if d and d.isdigit() else 0)

    def transitions(self):
        return sum(1 for _, t in self.tracks for it in t if it.tag == "transitionitem")


def track_enabled(t):
    return (t.findtext("enabled", "TRUE") or "TRUE").strip().upper() != "FALSE"


def item_enabled(it):
    return (it.findtext("enabled", "TRUE") or "TRUE").strip().upper() != "FALSE"


# --------------------------------------------------------------------------- audio analysis

def ffmpeg_peaks(path, start=None, dur=None):
    """Decode audio to 16 kHz mono and return the peak sample value per 10 ms window."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error"]
    if start is not None:
        cmd += ["-ss", "%.4f" % start]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", "%.4f" % dur]
    cmd += ["-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    except FileNotFoundError:
        die("ffmpeg is not installed or not on PATH. Mac: `brew install ffmpeg`. "
            "Windows: `winget install ffmpeg`.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.stderr.decode("utf-8", "replace").strip()[:400])
    a = array.array("h")
    a.frombytes(out[: len(out) - (len(out) % 2)])
    if sys.byteorder == "big":
        a.byteswap()
    n = len(a) // SPW
    peaks = array.array("i", [0]) * n
    for i in range(n):
        seg = a[i * SPW:(i + 1) * SPW]
        hi = max(seg)
        lo = min(seg)
        peaks[i] = max(hi, -lo)
    return peaks


def peaks_from_xml(sq, nwin, warnings):
    """Rebuild the sequence's loudness map from the media files the XML references.
    Takes the loudest of all enabled audio tracks at each moment (= silence only when
    nobody is making sound on any track)."""
    out = array.array("i", [0]) * nwin
    cache = {}
    clips = []
    for kind, t in sq.tracks:
        if kind != "audio" or not track_enabled(t):
            continue
        for it in t:
            if it.tag != "clipitem" or not item_enabled(it):
                continue
            f = it.find("file")
            fid = f.get("id") if f is not None else None
            path = sq.files.get(fid)
            if not path:
                continue
            crate = rate_of(it) or sq.fps
            s, e = int(it.findtext("start", "-1")), int(it.findtext("end", "-1"))
            i_, o_ = int(it.findtext("in", "0")), int(it.findtext("out", "0"))
            if s < 0 or e < 0:
                continue
            clips.append((path, s, e, i_, crate))
    uniq = sorted(set(c[0] for c in clips))
    for k, path in enumerate(uniq, 1):
        if not os.path.exists(path):
            warn("media file not found, its audio is ignored for silence detection: %s "
                 "(pass --audio with a mixdown WAV instead)" % path, warnings)
            continue
        sys.stderr.write("  reading audio %d/%d: %s\n" % (k, len(uniq), os.path.basename(path)))
        try:
            cache[path] = ffmpeg_peaks(path)
        except RuntimeError as e:
            warn("could not decode %s: %s" % (path, e), warnings)
    seen = set()
    for path, s, e, i_, crate in clips:
        if path not in cache or (path, s, e, i_) in seen:
            continue
        seen.add((path, s, e, i_))
        src = cache[path]
        t0 = float(Fraction(s) / sq.fps)
        t1 = float(Fraction(e) / sq.fps)
        src0 = float(Fraction(i_) / crate)
        w0, w1 = int(round(t0 / WIN)), min(nwin, int(round(t1 / WIN)))
        off = int(round(src0 / WIN)) - w0
        for w in range(w0, w1):
            j = w + off
            if 0 <= j < len(src) and src[j] > out[w]:
                out[w] = src[j]
    return out


# --------------------------------------------------------------------------- edit decisions

def decide(words, peaks, fps, opt, warnings):
    nwin = len(peaks)
    speech = [w for w in words if not w["filler"]]
    fillers = [w for w in words if w["filler"]]

    # ---- threshold
    def wspan(w, pad=0.0):
        return max(0, int(math.floor((w["start"] - pad) / WIN))), min(nwin, int(math.ceil((w["end"] + pad) / WIN)))

    if opt.silence_db is not None:
        thr_db = opt.silence_db
        speech_db = noise_db = None
    else:
        sp = []
        for w in speech:
            a, b = wspan(w)
            if b > a:
                sp.append(max(peaks[a:b]))
        if not sp:
            die("could not measure speech loudness (no audio under the transcribed words). "
                "Check that the transcript belongs to this sequence.")
        speech_db = db(statistics.median(sp))
        first = int(words[0]["start"] / WIN)
        last = min(nwin, int(words[-1]["end"] / WIN))
        body = sorted(peaks[first:last]) or [1]
        noise_db = db(body[int(len(body) * 0.10)])
        thr_db = max(speech_db - 20.0, noise_db + 6.0)
        if thr_db > speech_db - 8.0:
            warn("the quiet parts are almost as loud as speech (music bed or noisy room?). "
                 "Pause trimming may find little; fillers glued to words will be marked, not cut.",
                 warnings)
    thr = amp(thr_db)

    # ---- window states: 0 quiet, 1 filler, 2 protected
    QUIET, FILL, PROT = 0, 1, 2
    st = bytearray(nwin)
    for w in speech:
        a, b = wspan(w, opt.word_pad)
        for i in range(a, b):
            st[i] = PROT
    filler_of = {}
    for k, w in enumerate(fillers):
        a, b = wspan(w)
        for i in range(a, b):
            # only the audible part of the filler's span is the filler; its quiet part is silence
            if st[i] != PROT and peaks[i] > thr:
                st[i] = FILL
                filler_of[i] = k
    # grow each filler through adjacent loud windows (the ASR span is often shorter than the sound)
    changed = True
    while changed:
        changed = False
        for i in range(1, nwin - 1):
            if st[i] == QUIET and peaks[i] > thr and (st[i - 1] == FILL or st[i + 1] == FILL):
                st[i] = FILL
                filler_of[i] = filler_of.get(i - 1, filler_of.get(i + 1))
                changed = True
    # loud sound nobody transcribed: protect it
    for i in range(nwin):
        if st[i] == QUIET and peaks[i] > thr:
            st[i] = PROT
    if not opt.fillers:
        # pauses-only mode: fillers stay, like any other sound
        for i in range(nwin):
            if st[i] == FILL:
                st[i] = PROT

    edge = int(round(opt.edge_guard / WIN))     # quiet windows required on each side of a filler
    margin = 2                                    # 20 ms of quiet kept at each cut edge

    def runs():
        """Gaps = maximal non-protected runs bounded by protected windows on both sides."""
        out, i = [], 0
        while i < nwin:
            if st[i] != PROT:
                j = i
                while j < nwin and st[j] != PROT:
                    j += 1
                if i > 0 and j < nwin:
                    out.append((i, j))
                i = j
            else:
                i += 1
        return out

    left_in = []   # fillers we could not cut safely
    # pass 1: fillers without quiet on both sides become protected (and get a marker)
    for (a, b) in runs():
        k = a
        while k < b:
            if st[k] == FILL:
                j = k
                while j < b and st[j] == FILL:
                    j += 1
                # one filler often dips below the threshold for a few ms: keep it one filler
                while True:
                    q = j
                    while q < b and st[q] == QUIET:
                        q += 1
                    if q < b and st[q] == FILL and q - j < edge:
                        for i in range(j, q):
                            st[i] = FILL
                        j = q
                        while j < b and st[j] == FILL:
                            j += 1
                    else:
                        break
                lead = 0
                i = k - 1
                while i >= a and st[i] == QUIET:
                    lead += 1
                    i -= 1
                trail = 0
                i = j
                while i < b and st[i] == QUIET:
                    trail += 1
                    i += 1
                # quiet must separate the filler from protected sound (or another filler) on both sides
                if lead < edge or trail < edge:
                    for i in range(k, j):
                        st[i] = PROT
                    left_in.append((k * WIN, j * WIN, "no silence between the filler and the next word"
                                    if trail < edge else "no silence between the previous word and the filler"))
                k = j
            else:
                k += 1

    removals = []
    for (a, b) in runs():
        has_f = any(st[i] == FILL for i in range(a, b))
        length = (b - a) * WIN
        if not has_f and (not opt.pauses or length <= opt.max_pause):
            continue
        q0 = 0
        while a + q0 < b and st[a + q0] == QUIET:
            q0 += 1
        q1 = 0
        while b - 1 - q1 >= a and st[b - 1 - q1] == QUIET:
            q1 += 1
        keep_a = int(round(opt.keep_after / WIN))
        keep_b = int(round(opt.keep_before / WIN))
        if has_f:
            head = min(keep_a, q0 - margin)
            tail = min(keep_b, q1 - margin)
            # a filler inside a short gap: only take the filler, leave the natural air
            if not opt.pauses or length <= opt.max_pause:
                # keep everything except the filler run(s) plus the quiet strictly between them
                head = max(head, q0 - margin)
                tail = max(tail, q1 - margin)
        else:
            head, tail = keep_a, keep_b
        r0, r1 = a + head, b - tail
        if r1 <= r0:
            continue
        kind = "filler" if has_f else "pause"
        removals.append([r0 * WIN, r1 * WIN, kind, a * WIN, b * WIN])

    # ---- to whole frames, inward, verified
    fr = []
    for t0, t1, kind, ga, gb in removals:
        f0 = int(math.ceil(t0 * fps - 1e-6))
        f1 = int(math.floor(t1 * fps + 1e-6))
        if kind == "filler":
            # nudge outward-facing edges back into quiet if rounding pushed them into the filler
            def quiet_at(t):
                i = int(t / WIN)
                return 0 <= i < nwin and st[i] == QUIET
            if not quiet_at(float(Fraction(f0) / fps)) and quiet_at(float(Fraction(f0 - 1) / fps)) \
                    and float(Fraction(f0 - 1) / fps) >= ga:
                f0 -= 1
            if not quiet_at(float(Fraction(f1) / fps) - WIN) and quiet_at(float(Fraction(f1 + 1) / fps) - WIN) \
                    and float(Fraction(f1 + 1) / fps) <= gb:
                f1 += 1
        min_frames = max(1, int(round(opt.min_cut * float(fps))))
        if f1 - f0 < min_frames:
            continue
        fr.append([f0, f1, kind])
    fr.sort()
    merged = []
    for r in fr:
        if merged and r[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r[1])
            if r[2] == "filler":
                merged[-1][2] = "filler"
        else:
            merged.append(r)

    # every filler that was not cut gets a marker, whatever the reason
    for w in fillers:
        covered = any(Fraction(f0) / fps <= w["start"] + 0.02 and Fraction(f1) / fps >= w["end"] - 0.02
                      or (Fraction(f0) / fps < w["end"] and Fraction(f1) / fps > w["start"]
                          and min(w["end"], Fraction(f1) / fps) - max(w["start"], Fraction(f0) / fps)
                          >= 0.5 * (w["end"] - w["start"]))
                      for f0, f1, _ in merged)
        flagged = any(t0 < w["end"] + 0.05 and t1 > w["start"] - 0.05 for t0, t1, _ in left_in)
        if not covered and not flagged:
            left_in.append((w["start"], w["end"], "the filler overlaps the words around it in the transcript"))
    left_in.sort()

    info = {"threshold_db": round(thr_db, 1),
            "speech_db": None if speech_db is None else round(speech_db, 1),
            "noise_db": None if noise_db is None else round(noise_db, 1),
            "fillers_in_transcript": len(fillers)}
    return merged, left_in, st, info


def verify(removals, words, peaks, st, fps, thr_db):
    """Independent checks on the final frame-level removals."""
    problems = []
    thr = amp(thr_db)
    nwin = len(peaks)
    speech = [w for w in words if not w["filler"]]
    for f0, f1, kind in removals:
        t0, t1 = float(Fraction(f0) / fps), float(Fraction(f1) / fps)
        for w in speech:
            if w["start"] < t1 and w["end"] > t0:
                problems.append("cut %s-%s overlaps the word %r" % (timecode(f0, fps), timecode(f1, fps), w["text"]))
                break
        for t in (t0, t1):
            i = int(t / WIN)
            lo, hi = max(0, i - 2), min(nwin, i + 2)
            if lo < hi and max(peaks[lo:hi]) > thr:
                problems.append("cut edge at %s is not in silence" % timecode(int(round(t * fps)), fps))
    return problems


# --------------------------------------------------------------------------- applying the cuts

class Ripple:
    def __init__(self, removals):
        self.r = [(a, b) for a, b, _ in removals]

    def removed_before(self, f):
        tot = 0
        for a, b in self.r:
            if b <= f:
                tot += b - a
            elif a < f:
                tot += f - a
        return tot

    def map(self, f):
        return f - self.removed_before(f)

    def keep_pieces(self, s, e):
        pieces, cur = [], s
        for a, b in self.r:
            if b <= cur or a >= e:
                continue
            if a > cur:
                pieces.append((cur, a))
            cur = max(cur, b)
        if cur < e:
            pieces.append((cur, e))
        return pieces


def set_text(el, tag, value):
    c = el.find(tag)
    if c is not None:
        c.text = str(value)


def strip_to_reference(el):
    """<file id=x>...</file> -> <file id=x/> (and the same for nested <sequence>)."""
    for tag in ("file", "sequence"):
        for c in el.findall(tag):
            if c.get("id") and len(c):
                for sub in list(c):
                    c.remove(sub)
                c.text = None


def apply(sq, removals, warnings):
    rp = Ripple(removals)
    fps = sq.fps
    piece_ids = {}          # original clipitem id -> [new ids]
    keyframed = 0
    for kind, t in sq.tracks:
        new_children = []
        for it in list(t):
            t.remove(it)
            if it.tag not in ("clipitem", "generatoritem"):
                if it.tag == "transitionitem":
                    continue
                new_children.append(it)
                continue
            s, e = int(it.findtext("start", "-1")), int(it.findtext("end", "-1"))
            if s < 0 or e < 0:
                die("a clip on a %s track has no fixed start/end (it touches a transition). "
                    "Nest your sequence first (select all > right-click > Nest) and export again." % kind)
            pieces = rp.keep_pieces(s, e)
            crate = rate_of(it) or fps
            tpf = ticks_per_frame(crate)
            i0 = int(it.findtext("in", "0"))
            oid = it.get("id")
            ids = []
            if len(pieces) > 1 and any(True for _ in it.iter("keyframe")):
                keyframed += 1
            for k, (a, b) in enumerate(pieces):
                c = copy.deepcopy(it) if len(pieces) > 1 else it
                nin = i0 + (a - s)
                nout = nin + (b - a)
                set_text(c, "start", rp.map(a))
                set_text(c, "end", rp.map(a) + (b - a))
                set_text(c, "in", nin)
                set_text(c, "out", nout)
                # Premiere trusts these over <in>/<out>; stale values break the import
                set_text(c, "pproTicksIn", nin * tpf)
                set_text(c, "pproTicksOut", nout * tpf)
                if len(pieces) > 1:
                    nid = "%s-p%d" % (oid, k + 1) if oid else None
                    if nid:
                        c.set("id", nid)
                    if k > 0:
                        strip_to_reference(c)
                    ids.append(nid)
                else:
                    ids.append(oid)
                new_children.append(c)
            if oid:
                piece_ids[oid] = ids
        for c in new_children:
            t.append(c)
    if keyframed:
        warn("%d clips with keyframes (volume/effects animation) were split; their animation may "
             "shift. To keep it intact, nest the sequence before exporting." % keyframed, warnings)

    # clip index of every clip in its track, for <link> elements
    index_of = {}
    track_of = {}
    for ti, (kind, t) in enumerate(sq.tracks):
        n = 0
        for it in t:
            if it.tag in ("clipitem", "generatoritem"):
                n += 1
                if it.get("id"):
                    index_of[it.get("id")] = n
    # rebuild links: piece k links to piece k of each linked clip (when counts match)
    by_id = {}
    for _, t in sq.tracks:
        for it in t:
            if it.get("id"):
                by_id[it.get("id")] = it
    for oid, ids in piece_ids.items():
        for k, nid in enumerate(ids):
            el = by_id.get(nid)
            if el is None:
                continue
            for ln in el.findall("link"):
                ref = ln.findtext("linkclipref")
                tgt = piece_ids.get(ref)
                if tgt is None:
                    continue
                if len(tgt) != len(ids):
                    el.remove(ln)
                    continue
                set_text(ln, "linkclipref", tgt[k])
                if tgt[k] in index_of:
                    set_text(ln, "clipindex", index_of[tgt[k]])

    # sequence markers: shift, drop the ones inside removed spans
    for m in list(sq.seq.findall("marker")):
        try:
            f = int(m.findtext("in", "-1"))
        except ValueError:
            continue
        inside = any(a <= f < b for a, b, _ in removals)
        if inside:
            sq.seq.remove(m)
        else:
            set_text(m, "in", rp.map(f))
            o = m.findtext("out", "-1")
            if o and o.lstrip("-").isdigit() and int(o) >= 0:
                set_text(m, "out", rp.map(int(o)))
    return rp


def add_marker(seq_el, frame, name, comment):
    m = ET.SubElement(seq_el, "marker")
    ET.SubElement(m, "comment").text = comment
    ET.SubElement(m, "name").text = name
    ET.SubElement(m, "in").text = str(frame)
    ET.SubElement(m, "out").text = "-1"


def check_tracks(sq):
    problems = []
    for ti, (kind, t) in enumerate(sq.tracks, 1):
        last = None
        for it in t:
            if it.tag not in ("clipitem", "generatoritem"):
                continue
            s, e = int(it.findtext("start")), int(it.findtext("end"))
            i_, o_ = int(it.findtext("in")), int(it.findtext("out"))
            if e - s != o_ - i_:
                problems.append("%s track %d: clip length mismatch at %d" % (kind, ti, s))
            if last is not None and s < last:
                problems.append("%s track %d: clips overlap at frame %d" % (kind, ti, s))
            last = e
    return problems


# --------------------------------------------------------------------------- report

def context(words, t0, t1, n=5):
    before = [w for w in words if w["end"] <= t0 + 0.05][-n:]
    inside = [w for w in words if w["start"] < t1 and w["end"] > t0]
    after = [w for w in words if w["start"] >= t1 - 0.05][:n]
    def fmt(ws):
        return " ".join("um/uh" if w["filler"] and not w["text"] else w["text"] for w in ws)
    return fmt(before), fmt(inside), fmt(after)


def write_report(path, rows, summary, warnings, problems):
    css = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e4e1da;--card:#fff;--cut:#1f7a4d;--pause:#3b5bdb;--check:#b54708}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#a3a29c;--line:#2e2d2a;--card:#1c1b19;--cut:#4cc38a;--pause:#8ea2ff;--check:#f5a524}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}p.sub{color:var(--mut);margin:0 0 24px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.stat b{display:block;font-size:24px}.stat span{color:var(--mut);font-size:13px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:16px}
.box.warn{border-color:var(--check)}h2{font-size:17px;margin:28px 0 10px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}.filters button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:13px}
.filters button.on{background:var(--fg);color:var(--bg)}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}td.tc{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}
.k{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;white-space:nowrap;border:1px solid currentColor}
.k.filler{color:var(--cut)}.k.pause{color:var(--pause)}.k.check{color:var(--check)}
.ctx{color:var(--mut)}.ctx mark{background:none;color:var(--fg);font-weight:700;text-decoration:line-through}.ctx mark.keep{text-decoration:none;border-bottom:2px solid var(--check)}
"""
    def row_html(r):
        b, i, a = (html.escape(x) for x in r["context"])
        cls = "keep" if r["kind"] == "check" else ""
        mid = '<mark class="%s">%s</mark>' % (cls, i or "&middot; silence &middot;")
        label = {"filler": "filler cut", "pause": "pause shortened", "check": "check by ear"}[r["kind"]]
        return ('<tr data-k="%s"><td>%d</td><td><span class="k %s">%s</span></td><td class="tc">%s</td>'
                '<td class="tc">%s</td><td class="tc">%s</td><td class="ctx">%s %s %s</td></tr>'
                % (r["kind"], r["n"], r["kind"], label, r["orig_tc"], r["new_tc"],
                   ("%.2fs" % r["removed"]) if r["removed"] else "&ndash;", b, mid, a))
    s = summary
    body = """<main>
<h1>Cleanup report</h1>
<p class="sub">%(name)s &middot; %(fps)s fps &middot; podcast_clean.py %(ver)s</p>
<div class="stats">
<div class="stat"><b>%(before)s</b><span>length before</span></div>
<div class="stat"><b>%(after)s</b><span>length after (%(saved)s removed)</span></div>
<div class="stat"><b>%(n_f)d</b><span>fillers cut</span></div>
<div class="stat"><b>%(n_p)d</b><span>pauses shortened</span></div>
<div class="stat"><b>%(n_c)d</b><span>spots to check by ear</span></div>
</div>
""" % s
    if problems:
        body += '<div class="box warn"><b>Self-check found problems. Do not use this cut before reading these:</b><ul>%s</ul></div>' % \
            "".join("<li>%s</li>" % html.escape(p) for p in problems)
    else:
        body += '<div class="box"><b>Self-check passed.</b> No cut touches a transcribed word, every cut edge sits in silence, every track keeps its sync.</div>'
    if warnings:
        body += '<div class="box warn"><b>Warnings</b><ul>%s</ul></div>' % "".join("<li>%s</li>" % html.escape(w) for w in warnings)
    body += """<div class="box"><b>How to read this.</b> Times under <i>original</i> are on your old sequence; times under <i>new</i> are on the cleaned one.
Struck-through words were removed. <span class="k check">check by ear</span> rows are fillers the script left in because they run straight into a word;
jump to the <i>new</i> time and decide yourself. Silence threshold used: %(thr)s dBFS%(levels)s.</div>
<h2>Every edit</h2>
<div class="filters"><button class="on" data-f="all">All</button><button data-f="filler">Fillers cut</button><button data-f="pause">Pauses</button><button data-f="check">Check by ear</button></div>
<div class="tw"><table><thead><tr><th>#</th><th>What</th><th>Original</th><th>New</th><th>Removed</th><th>Words around it</th></tr></thead><tbody>
""" % s
    body += "".join(row_html(r) for r in rows)
    body += """</tbody></table></div></main>
<script>
document.querySelectorAll('.filters button').forEach(function(b){b.onclick=function(){
document.querySelectorAll('.filters button').forEach(function(x){x.classList.remove('on')});b.classList.add('on');
var f=b.dataset.f;document.querySelectorAll('tbody tr').forEach(function(r){r.style.display=(f==='all'||r.dataset.k===f)?'':'none'})}})
</script>"""
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Cleanup report</title><style>%s</style></head><body>%s</body></html>' % (css, body))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


# --------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Remove ums, uhs and long pauses from a Premiere sequence (FCP XML in, FCP XML out).")
    ap.add_argument("--xml", required=True, help="sequence exported from Premiere as Final Cut Pro XML")
    ap.add_argument("--transcript", required=True, help="the same sequence's transcript, exported from the Text panel as JSON")
    ap.add_argument("--audio", help="optional mixdown of the same sequence (WAV etc). Default: read the media files in the XML")
    ap.add_argument("--out", help="output XML (default: <xml name>-cleaned.xml next to the input)")
    ap.add_argument("--report", help="output HTML report (default: <out>-report.html)")
    ap.add_argument("--mode", choices=["both", "fillers", "pauses"], default="both", help="what to remove (default: both)")
    ap.add_argument("--max-pause", type=float, default=1.0, help="pauses longer than this (s) get shortened (default 1.0)")
    ap.add_argument("--keep-after", type=float, default=0.35, help="silence kept after the last word of a shortened pause (default 0.35)")
    ap.add_argument("--keep-before", type=float, default=0.25, help="silence kept before the next word (default 0.25)")
    ap.add_argument("--silence-db", type=float, default=None, help="force the silence threshold in dBFS (default: measured from your audio)")
    ap.add_argument("--edge-guard", type=float, default=0.04, help="silence needed on each side of a filler before it is cut (default 0.04 s)")
    ap.add_argument("--word-pad", type=float, default=0.04, help="extra protection around every transcribed word (default 0.04 s)")
    ap.add_argument("--min-cut", type=float, default=0.10, help="ignore removals shorter than this (default 0.10 s)")
    ap.add_argument("--dry-run", action="store_true", help="write the report only, no XML")
    ap.add_argument("--version", action="version", version=VERSION)
    opt = ap.parse_args(argv)
    opt.fillers = opt.mode in ("both", "fillers")
    opt.pauses = opt.mode in ("both", "pauses")
    warnings = []

    base = os.path.splitext(opt.xml)[0]
    out = opt.out or base + "-cleaned.xml"
    report = opt.report or os.path.splitext(out)[0] + "-report.html"
    edits_json = os.path.splitext(out)[0] + "-edits.json"

    sq = Seq(opt.xml)
    fps = sq.fps
    if sq.transitions():
        die("the sequence has %d transition(s). Nest it first (select everything > right-click > Nest), "
            "put the nest in a new sequence, and export that sequence. Nothing inside the nest is "
            "touched, so your transitions and effects survive." % sq.transitions())
    words = load_transcript(opt.transcript)
    dur_f = sq.duration_frames()
    dur_s = float(Fraction(dur_f) / fps)
    if words[-1]["end"] > dur_s + 2.0:
        die("the transcript runs to %.1fs but the sequence is only %.1fs long. The transcript must be "
            "exported from THIS sequence (not from the raw files or an older version)." % (words[-1]["end"], dur_s))
    if words[-1]["end"] < dur_s * 0.6 and dur_s - words[-1]["end"] > 60:
        warn("the transcript ends at %.0fs but the sequence runs %.0fs. If the sequence was edited after "
             "transcribing, re-transcribe it first." % (words[-1]["end"], dur_s), warnings)

    nwin = int(math.ceil(dur_s / WIN)) + 1
    print("Analysing audio...")
    if opt.audio:
        if not os.path.exists(opt.audio):
            die("audio file not found: %s" % opt.audio)
        peaks = ffmpeg_peaks(opt.audio)
        if abs(len(peaks) * WIN - dur_s) > 1.0:
            warn("the audio file is %.1fs long but the sequence is %.1fs. Export the mixdown from the "
                 "whole sequence, starting at 00:00." % (len(peaks) * WIN, dur_s), warnings)
        if len(peaks) < nwin:
            peaks.extend([0] * (nwin - len(peaks)))
        peaks = peaks[:nwin]
    else:
        peaks = peaks_from_xml(sq, nwin, warnings)
    if max(peaks) == 0:
        die("found no audio at all. Pass --audio with a WAV mixdown of the sequence.")

    print("Deciding edits...")
    removals, left_in, st, info = decide(words, peaks, fps, opt, warnings)
    problems = verify(removals, words, peaks, st, fps, info["threshold_db"])

    rp = Ripple(removals)
    removed_f = sum(b - a for a, b, _ in removals)
    rows = []
    for f0, f1, kind in removals:
        t0, t1 = float(Fraction(f0) / fps), float(Fraction(f1) / fps)
        rows.append({"kind": kind, "f0": f0, "f1": f1, "orig_tc": timecode(f0, fps),
                     "new_tc": timecode(rp.map(f0), fps), "removed": t1 - t0,
                     "context": context(words, t0, t1)})
    markers = []
    for t0, t1, why in left_in:
        f = int(round(t0 * fps))
        if opt.fillers:
            rows.append({"kind": "check", "f0": f, "f1": f, "orig_tc": timecode(f, fps),
                         "new_tc": timecode(rp.map(f), fps), "removed": 0,
                         "context": context(words, t0, t1), "why": why})
            markers.append({"time_seconds": round(float(Fraction(rp.map(f)) / fps), 3),
                            "timecode": timecode(rp.map(f), fps), "name": "Filler left in: check",
                            "comment": why})
    rows.sort(key=lambda r: r["f0"])
    for n, r in enumerate(rows, 1):
        r["n"] = n

    if not opt.dry_run:
        apply(sq, removals, warnings)
        for m in markers:
            add_marker(sq.seq, int(round(m["time_seconds"] * float(fps))), m["name"], m["comment"])
        new_dur = dur_f - removed_f
        set_text(sq.seq, "duration", new_dur)
        name_el = sq.seq.find("name")
        if name_el is not None:
            name_el.text = (sq.name or "Sequence") + " - cleaned"
        u = sq.seq.find("uuid")
        if u is not None:
            u.text = str(uuid.uuid4())
        problems += check_tracks(sq)
        xml_bytes = ET.tostring(sq.root, encoding="unicode")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
            fh.write(xml_bytes)
        ET.parse(out)  # must re-read cleanly

    summary = {"name": html.escape(sq.name or ""), "fps": "%.3f" % float(fps), "ver": VERSION,
               "before": timecode(dur_f, fps)[:-3], "after": timecode(dur_f - removed_f, fps)[:-3],
               "saved": "%dm %02ds" % divmod(int(round(removed_f / float(fps))), 60),
               "n_f": sum(1 for r in rows if r["kind"] == "filler"),
               "n_p": sum(1 for r in rows if r["kind"] == "pause"),
               "n_c": sum(1 for r in rows if r["kind"] == "check"),
               "thr": info["threshold_db"],
               "levels": "" if info["speech_db"] is None else
               " (speech peaks around %s dBFS, room tone around %s dBFS)" % (info["speech_db"], info["noise_db"])}
    write_report(report, rows, summary, warnings, problems)
    with open(edits_json, "w", encoding="utf-8") as fh:
        json.dump({"version": VERSION, "sequence": sq.name, "fps": float(fps), "settings": vars(opt),
                   "levels": info, "removed_seconds": round(removed_f / float(fps), 3),
                   "edits": [{k: v for k, v in r.items() if k != "n"} for r in rows],
                   "markers_for_new_sequence": markers, "warnings": warnings, "self_check_problems": problems},
                  fh, indent=1, default=str)

    print("\nDone.")
    print("  fillers cut:        %d" % summary["n_f"])
    print("  pauses shortened:   %d" % summary["n_p"])
    print("  left in, check:     %d" % summary["n_c"])
    print("  length:             %s -> %s (%s removed)" % (summary["before"], summary["after"], summary["saved"]))
    if not opt.dry_run:
        print("  new sequence XML:   %s" % out)
    print("  report:             %s" % report)
    print("  edits + markers:    %s" % edits_json)
    if problems:
        print("\nSELF-CHECK FOUND %d PROBLEM(S). Read the report before importing." % len(problems))
        return 1
    print("  self-check:         passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
