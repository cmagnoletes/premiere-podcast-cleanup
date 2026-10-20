# Tuning

The defaults are made for conversation: two or three people talking, natural rhythm. Change one
thing at a time and compare.

| Setting | Default | What it does | Change it when |
|---|---|---|---|
| `--mode` | `both` | `fillers` = only ums/uhs; `pauses` = only pauses | you want one pass without the other |
| `--max-pause` | `1.0` s | pauses longer than this get shortened; shorter ones are left alone | the episode feels rushed → `1.5`; still slow → `0.8` |
| `--keep-after` | `0.35` s | silence kept after the last word before a shortened pause | joins feel clipped → `0.45` |
| `--keep-before` | `0.25` s | silence kept before the next word | the next line starts too abruptly → `0.35` |
| `--silence-db` | measured | anything quieter than this (dBFS, peak) counts as silence | music bed or noisy room (see below) |
| `--edge-guard` | `0.04` s | silence needed on each side of an um before it is cut | you hear clicks at filler cuts → `0.06` |
| `--word-pad` | `0.04` s | extra protection around every transcribed word | word starts or ends sound nibbled → `0.08` |
| `--min-cut` | `0.10` s | removals shorter than this are skipped | rarely |
| `--audio` | none | use a mixdown WAV instead of reading the media files | media is offline or on another machine |
| `--dry-run` | off | report only, no XML | to preview what would happen |

## The silence threshold

The report prints a line like *"Silence threshold used: -34 dBFS (speech peaks around -14 dBFS,
room tone around -78 dBFS)"*. By default the threshold is 20 dB under the speech level (but always
6 dB above the room tone).

- **Music under the conversation, or a noisy room:** the room/bed level is close to the speech level
  and almost nothing counts as silence. Set `--silence-db` a few dB above the bed, e.g. room at
  -40 → `--silence-db -35`. Keep it at least 8 dB under the speech level, or speech gets treated as silence
  (the word protection still keeps transcribed words safe, but untranscribed sounds won't be).
- **Very quiet recording:** the measured threshold follows your levels; nothing to do.

## Where to clean in your workflow

Clean **after** your cuts and camera switches, **before** music, sound design and graphics. The
script cuts every track at the same moment, so a music bed on its own track would be chopped at
every edit too. If you must clean a sequence that already has music, mute or remove the music
track before exporting, or nest the dialogue and cameras and clean the nest.
