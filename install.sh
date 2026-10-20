#!/usr/bin/env bash
# Installs the podcast-cleanup skill into Claude Code (Mac/Linux). Windows: see docs/SETUP.md.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILLS="$HOME/.claude/skills"
TARGET="$SKILLS/podcast-cleanup"

command -v python3 >/dev/null || { echo "Python 3 is missing. Install it from python.org or with Homebrew."; exit 1; }
command -v ffmpeg  >/dev/null || { echo "ffmpeg is missing. Mac: brew install ffmpeg"; exit 1; }

mkdir -p "$SKILLS"
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
  echo "$TARGET already exists and is not a link. Move it away first, then rerun."; exit 1
fi
ln -sfn "$HERE/skills/podcast-cleanup" "$TARGET"
echo "Linked $TARGET -> $HERE/skills/podcast-cleanup"

echo "Running the tests..."
if python3 -m unittest discover -s "$HERE/tests" >/dev/null 2>&1; then
  echo "Tests passed."
else
  echo "Tests FAILED. Run: python3 -m unittest discover -s \"$HERE/tests\"  to see why."; exit 1
fi
echo
echo "Done. Restart Claude Code, open Premiere with the MCP Bridge started, and say:"
echo "  Clean up the active sequence in Premiere."
