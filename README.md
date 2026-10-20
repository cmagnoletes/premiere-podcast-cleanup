# Premiere Podcast Cleanup

Remove the ums, uhs and dead air from a podcast edit in **Adobe Premiere Pro**, with
**Claude Code** doing the busywork through the [Premiere Pro MCP](https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP).

You say *"clean up this episode"*. A few minutes later there is a new sequence next to yours,
`<episode> - cleaned`, with:

- every **um / uh** that has silence around it removed,
- every **pause longer than 1 second** shortened to about half a second,
- every camera and mic track cut at the same frame, so nothing drifts out of sync,
- a **marker** on each um that runs straight into a word (those need your ear),
- an **HTML report** listing every edit, its timecode, and the words around it.

Your original sequence is never touched. If you don't like the result, delete the new sequence.

> Built from the cleanup step of the editing pipeline I use on client YouTube videos
> ([carlosmagno.me](https://carlosmagno.me)). The safety rules in it come from things that went
> wrong on real edits.

---

## What you need

| | |
|---|---|
| Adobe Premiere Pro | a recent version with the Text panel transcript (tested on Premiere Pro 2026, v26) |
| Claude Code | [claude.com/claude-code](https://claude.com/claude-code) |
| Node.js 18+ | for the Premiere MCP |
| Python 3.9+ | Mac has it; Windows: `winget install Python.Python.3.12` |
| ffmpeg | Mac: `brew install ffmpeg` · Windows: `winget install Gyan.FFmpeg` |

Mac is the tested path. **On Windows:** use `install.ps1` instead of `install.sh`, `py` instead of `python3`, and a
Windows temp folder for the MCP bridge (it ignores `/tmp`). Full steps: [docs/SETUP.md → Windows](docs/SETUP.md#windows).

## Set it up (once, ~15 minutes)

1. **Install the Premiere MCP** and connect it to Claude Code: [docs/SETUP.md](docs/SETUP.md#1-the-premiere-mcp)
2. **Install this skill:**
   ```bash
   git clone https://github.com/cmagnoletes/premiere-podcast-cleanup.git
   cd premiere-podcast-cleanup
   ./install.sh
   ```
   Windows: `powershell -ExecutionPolicy Bypass -File .\install.ps1`
3. **Try it on the demo** (no Premiere needed, 10 seconds):
   ```bash
   python3 tests/make_fixture.py ~/Desktop/cleanup-demo
   python3 skills/podcast-cleanup/scripts/podcast_clean.py --xml ~/Desktop/cleanup-demo/demo.xml --transcript ~/Desktop/cleanup-demo/demo.json
   open ~/Desktop/cleanup-demo/demo-cleaned-report.html
   ```

## Use it (every episode)

1. Finish your edit in Premiere (cuts, camera switches, intro). Clean last, before music and graphics.
2. Transcribe the sequence: `Window > Text` → **Transcript** → **Transcribe sequence**, with every mic included.
3. Open Claude Code and say:
   > Clean up the active sequence in Premiere.
4. Claude asks you to export the transcript as JSON (`...` menu → **Export transcript** → **JSON**),
   exports the sequence itself, runs the cleanup, imports `<episode> - cleaned`, adds the markers,
   and opens the report.
5. Watch a few of the edits in the report and jump through the markers. Done.

Prefer to run it yourself without Claude? See [Manual use](#manual-use).

## How it decides

Three inputs from the same sequence: the **XML** (where every clip sits), the **transcript**
(where every word sits), and the **audio** (where it is actually quiet).

1. **A cut never touches a transcribed word.** Only the filler itself and silence can go.
2. **A cut never touches a sound the transcript can't explain.** Laughter, a cough, a "mm-hm"
   the transcript missed: loud and unexplained means protected.
3. **A filler goes only if there is silence on both sides of it.** Cutting an "um" that runs
   into the next word chops the word. Those become markers.
4. **Long pauses are shortened, not removed.** It keeps 0.35 s after the last word and 0.25 s
   before the next one, so speech keeps breathing. Short pauses are left alone.
5. **Whole frames, every track, same moment.** No speed changes, no re-encoding, no drift.
6. **It checks its own work** before writing anything, and tells you if a check fails.

The silence threshold is measured from your audio (about 20 dB below the speech level), so
quiet and loud recordings both work. All the knobs: [docs/TUNING.md](docs/TUNING.md).

## What it won't do

- Remove "like", "you know", "I mean". Those are words, and often they carry meaning. Cut them by hand.
- Fix crosstalk, or ums that overlap the other person talking.
- Work on a sequence with transitions. Nest the sequence first (see [Troubleshooting](docs/TROUBLESHOOTING.md)).
- Replace your ear. Watch the result before you publish.

## Manual use

```bash
python3 skills/podcast-cleanup/scripts/podcast_clean.py \
  --xml episode.xml \
  --transcript episode.json \
  [--audio episode-mix.wav] [--mode both|fillers|pauses] [--max-pause 1.0] [--dry-run]
```

- `episode.xml`: `File > Export > Final Cut Pro XML...`
- `episode.json`: Text panel → Transcript → `...` → Export transcript → JSON
- `episode-mix.wav` (only if your media files are not on this computer): `File > Export > Media` → Waveform Audio → Entire Sequence

Then `File > Import` the `-cleaned.xml` into Premiere.

## Files

```
skills/podcast-cleanup/SKILL.md            what Claude follows
skills/podcast-cleanup/scripts/podcast_clean.py   the cleanup (Python standard library + ffmpeg)
docs/SETUP.md          MCP + skill install, Mac and Windows
docs/TUNING.md         every setting, with when to change it
docs/TROUBLESHOOTING.md
tests/                 a fake two-mic podcast + 13 tests: python3 -m unittest discover tests
```

## Tested

- 13 automated tests on a fake two-mic podcast (every case: pause, clean um, glued um, untranscribed laugh).
- A real 36-minute, six-file recording: 6m18s of dead air removed in about 4 seconds; the cleaned XML
  imported into Premiere Pro 2026 and re-exported with all 142 clips per track at exactly the
  authored positions, A/V links and markers intact.

## Credits

- Premiere control: [Adobe Premiere Pro MCP](https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP) by Het Patel.
- Made by [Carlos Magno](https://carlosmagno.me). MIT license.
