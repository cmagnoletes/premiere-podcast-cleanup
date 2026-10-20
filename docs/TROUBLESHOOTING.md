# Troubleshooting

## The MCP doesn't answer

Claude says it can't reach Premiere, or tool calls time out:

1. Premiere is open **and a project is open**.
2. The panel is running: `Window > Extensions > MCP Bridge (CEP)` → **Start Bridge**.
3. The panel's Temp Directory is exactly `/tmp/premiere-mcp-bridge` (or whatever you passed as
   `PREMIERE_TEMP_DIR`). One character off and they never meet.
4. The panel is missing from `Window > Extensions`: rerun `npm run setup:mac` in the MCP folder and
   restart Premiere.
5. You changed the MCP config: restart Claude Code.
6. Still stuck: in the panel click **Run Diagnostics**, then `npm run setup:doctor` in the MCP folder.

None of this blocks the cleanup itself: you can always run the script by hand
([README → Manual use](../README.md#manual-use)) and `File > Import` the result.

## "the sequence has N transition(s)"

Select everything in the sequence → right-click → **Nest**. Create a new sequence from that nest
(drag it onto the New Item button), transcribe the new sequence, and clean it. The inside of the nest
is never touched, so transitions, effects, multicam and keyframes survive.

## "the transcript runs to X s but the sequence is only Y s long"

The transcript came from a different sequence (often the raw recording), or from this sequence
before you edited it. Re-transcribe the sequence you are cleaning and export again.

## "media file not found"

The XML points to footage this computer can't see (drive not mounted, files moved, project made on
another machine). Export a mixdown: `File > Export > Media` → **Waveform Audio** → range **Entire
Sequence** → run again with `--audio that.wav`.

## The import fails, or the imported sequence looks wrong

- Make sure you imported the `-cleaned.xml`, not the original.
- Clips offline (red): relink to the same files your original uses.
- A clip with **volume or effect keyframes** was split: its animation may land in the wrong place.
  The report warns about this. Nest before cleaning to avoid it.
- Anything else: open an issue with the report HTML and the `-edits.json` (no media needed).

## It cut too much / too little

See [TUNING.md](TUNING.md). The two settings that matter most are `--max-pause` and the
`--keep-*` pair.

## An um is still in

Either it is a marker (an um glued to a word: cut it by hand or keep it), or the transcript didn't
mark it. Premiere transcribes many ums as blank words tagged `disfluency`, which the script finds;
some it writes as real words or skips. Filler words that are real words ("like", "so") are never
removed automatically.

## Two speakers, but only one got protected

Premiere's transcription can analyse only one audio track. Before transcribing, check the
transcription options include every mic track (or transcribe a sequence where the mics are mixed).
A missing speaker shows up as the other person's words getting cut: check the first run carefully.
