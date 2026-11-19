#!/bin/bash
# Double-click me: asks for a video link (or file), makes 3 clips, opens the folder.
cd "$(dirname "$0")" && source .venv/bin/activate
LINK=$(osascript -e 'text returned of (display dialog "Paste a video link (or drag a file path):" default answer "" with title "Icarus Clipper")') || exit 0
python clip.py "$LINK" --top 3 --len 30 --model base && open out/
echo; read -n 1 -p "Done. Press any key to close."
