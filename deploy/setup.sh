#!/usr/bin/env bash
# Runs ON the Oracle server (Ubuntu 22.04/24.04, ARM or x86). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="$(pwd)"

echo "== system packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg python3-venv python3-pip fonts-dejavu-core curl

echo "== caption font (Anton, SIL Open Font License)"
mkdir -p assets/fonts
[ -f assets/fonts/Anton-Regular.ttf ] || curl -fsSL -o assets/fonts/Anton-Regular.ttf \
  https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf

echo "== python venv"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "== swap (helps Whisper + ffmpeg on bursts)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== warm up Whisper model"
.venv/bin/python -c "from clipper.config import load_config; from clipper.captions import _model; _model(load_config()['captions']['model'])"

echo "== systemd service"
sed -e "s#__APP__#$APP#g" -e "s#__USER__#$(whoami)#g" deploy/clipper.service | sudo tee /etc/systemd/system/clipper.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable clipper >/dev/null
sudo systemctl restart clipper
sleep 3
systemctl --no-pager --lines=5 status clipper || true
echo
echo "Done. Live logs:  journalctl -u clipper -f"
