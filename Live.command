#!/bin/bash
# Double-click me: asks for a Twitch channel, clips the live stream until you close the window.
cd "$(dirname "$0")" && source .venv/bin/activate
CH=$(osascript -e 'text returned of (display dialog "Twitch channel name (e.g. xqc):" default answer "" with title "Icarus Live Clipper")') || exit 0
open out/ 2>/dev/null || mkdir -p out && open out/
python live.py "twitch.tv/$CH" --credit "🎥 @$CH" --model base
