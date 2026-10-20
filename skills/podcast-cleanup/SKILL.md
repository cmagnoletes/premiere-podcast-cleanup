---
name: podcast-cleanup
description: Remove ums, uhs and long pauses from a podcast or talking-head edit in Adobe Premiere Pro, through the Premiere MCP. Builds a NEW cleaned sequence next to the original (never edits the original), cuts every camera and mic track at the same moment so sync holds, leaves any "um" that runs into a word as a marker to check by ear, and writes an HTML report of every edit. Use when the user says "clean up this episode", "remove the ums", "remove filler words", "cut the dead air", "tighten the pauses", "de-um this", or asks for a filler/silence pass in Premiere.
---

# Podcast cleanup (ums, uhs, long pauses)

You turn the user's Premiere sequence into a cleaned copy:

```
their sequence ──export XML (MCP)──┐
their transcript JSON (they export)├──► scripts/podcast_clean.py ──► cleaned XML ──import (MCP)──► "<name> - cleaned"
audio (read from their media files)┘                                  + report.html + edits.json (markers)
```

The script does the deciding. Premiere does the importing. **You never cut the user's original
sequence with MCP edit tools.** The cleaned sequence is a new one; the original stays untouched,
so the worst case is always "delete the new sequence and nothing happened".

## Before you start (check once per session)

1. **Premiere is open with the project, and the MCP answers.** Call `get_project_info`. If it fails,
   walk the user through: `Window > Extensions > MCP Bridge (CEP)` → temp directory
   `/tmp/premiere-mcp-bridge` → **Save Configuration** → **Start Bridge**. (Full setup is in the
   repo's `docs/SETUP.md`.)
2. **ffmpeg and Python 3 exist.** Run `ffmpeg -version` and `python3 --version` (on Windows,
   `python --version`). If ffmpeg is missing: Mac `brew install ffmpeg`, Windows `winget install ffmpeg`.
3. **A work folder.** Default `~/Podcast-Cleanup/<sequence name>/`. Every file of the run goes there.

## The run

### 1. Pick the sequence
Call `get_active_sequence`. Tell the user the name and length you see and confirm it is the one to
clean. If they have multiple episodes open, ask which one. Note the sequence id.

The sequence should start at 00:00:00:00. If it has **transitions** (crossfades, dips) the script
will refuse; tell them to select everything in the sequence → right-click → **Nest**, put that
nest in a fresh sequence, and clean that one. Nothing inside a nest is touched, so transitions,
effects, multicam and keyframes all survive.

### 2. Get the transcript (the user does this; MCP cannot)
Ask the user to:
1. Open `Window > Text`, **Transcript** tab, with the sequence active.
2. Click **Transcribe sequence** (or re-transcribe if they edited since). In the options, make sure
   **all mic tracks** are included (podcast: every speaker's track, or the mix track). Premiere
   can silently transcribe only one track, and then the other speaker's words are unprotected.
3. In the Transcript tab, open the **`...`** menu → **Export transcript** → choose **JSON**, and save
   it into the work folder.

Then check the file yourself: it must have `segments[].words[]` with `start` and `duration`. The
script also checks that the transcript belongs to this sequence (it refuses one that runs longer
than the sequence).

### 3. Export the sequence as XML
Call `export_as_fcp_xml` with the sequence id and `outputPath` = `<work folder>/<name>.xml`.
If the tool fails, ask the user: `File > Export > Final Cut Pro XML...` with the sequence selected.

### 4. Run the script
```bash
python3 "<this skill folder>/scripts/podcast_clean.py" \
  --xml "<work>/<name>.xml" --transcript "<work>/<name>.json"
```
It reads the audio straight from the media files the XML points to. If it warns that media files
were not found (footage on a drive that is not mounted, or the edit lives on another machine), ask
the user for a mixdown instead: `File > Export > Media`, format **Waveform Audio**, range **Entire
Sequence**, and add `--audio "<work>/<name>.wav"`.

Read the console summary and give it to the user in plain words: how many fillers cut, pauses
shortened, spots left to check, minutes saved. If the script printed **SELF-CHECK FOUND PROBLEMS**,
stop and read the problems out; do not import.

Useful options (all in `docs/TUNING.md`):
- `--mode fillers` only ums/uhs, keep every pause; `--mode pauses` only pauses
- `--max-pause 1.5` leave pauses shorter than 1.5 s alone (default 1.0)
- `--keep-after 0.45 --keep-before 0.3` keep more air in shortened pauses (default 0.35 / 0.25)
- `--dry-run` report only, no XML

### 5. Import the cleaned sequence
Call `import_fcp_xml` with `filePath` = the `-cleaned.xml`. A new sequence named
`<name> - cleaned` appears. Premiere may also add a second copy of each media clip in the Project
panel; that is normal for XML imports and harmless.

### 6. Check the markers
The cleaned XML carries one marker per "um" left in (`<name>-cleaned-edits.json` →
`markers_for_new_sequence`). Current Premiere keeps them on import, but some versions and import
paths drop them, and markers **cannot be deleted through the MCP**, so check before adding:
1. `set_active_sequence` to the NEW sequence. (`add_marker` and `list_markers` act on the ACTIVE
   sequence, whatever id you pass.)
2. `list_markers`. If every marker from the JSON is there (same times), you're done.
3. Only for the missing ones: `add_marker` with `time_seconds`, `name`, `comment`, one call at a time.

### 7. Hand it over
Open the report (`<name>-cleaned-report.html`) for the user. Tell them:
- the numbers, and that the original sequence is untouched;
- to play three or four of the edits listed in the report (the **New** column is the timecode on
  the cleaned sequence) to confirm the rhythm feels natural;
- to jump through the markers: each one is an "um" glued to a word. Removing those needs a human
  ear (or a different take), so the script left them in.

## Rules
- Never edit, ripple, razor or delete clips on the user's original sequence. Never delete a sequence.
- One writer at a time: do not run MCP edits in parallel against the same sequence.
- The transcript, the XML and the audio must all come from the SAME sequence, in its current state.
  If the user edits the sequence after transcribing, transcribe and export again.
- If a result sounds wrong, change the settings and run again on the original sequence. Never
  clean an already cleaned sequence twice with the same settings expecting a different result.
- Report what the script reported. Do not claim a cut is clean unless the self-check passed.

## When the user says it sounds off
| They say | Do |
|---|---|
| "too tight / rushed" | rerun with `--keep-after 0.45 --keep-before 0.35` or `--max-pause 1.5` |
| "still too slow" | `--max-pause 0.8 --keep-after 0.3 --keep-before 0.2` |
| "it cut a breath I liked" | raise `--max-pause`; breaths inside short pauses are never cut |
| "an um is still there" | it is a marker spot (glued to a word) or the transcript missed it; cut it by hand |
| "it chopped a word" | should not happen (self-check). Send the report + edits.json to the repo issues; meanwhile `--word-pad 0.08` |
| "nothing got cut" | music bed or loud room: read the report's levels line, then rerun with `--silence-db` a few dB ABOVE the room/bed level (e.g. `-28`). Higher = more counts as silence; never go within 8 dB of the speech level |
