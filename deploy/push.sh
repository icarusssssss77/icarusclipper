#!/usr/bin/env bash
# Runs on your Mac. Copies the clipper (incl. .env and secrets/) to the server and (re)starts it.
#   deploy/push.sh <server-ip>
set -euo pipefail
IP="${1:?usage: deploy/push.sh <server-ip>}"
KEY="$HOME/.ssh/clipper_oracle"
cd "$(dirname "$0")/.."
rsync -az --delete -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude .venv --exclude _seed --exclude output --exclude buffer --exclude __pycache__ \
  --exclude assets/fonts \
  ./ "ubuntu@$IP:~/Clipping/"
ssh -i "$KEY" "ubuntu@$IP" 'bash ~/Clipping/deploy/setup.sh'
