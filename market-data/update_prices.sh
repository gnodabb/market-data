#!/usr/bin/env bash
# Fetch prices and push prices.json to the GitHub repo. Run from cron.
set -euo pipefail

REPO_DIR="$HOME/market-data"          # local clone of the GitHub repo
VENV="$HOME/market-data-venv"         # python venv with yfinance
LOG="$HOME/market-data.log"

{
  echo "=== $(date -Is) ==="
  cd "$REPO_DIR"
  git pull --quiet --rebase
  "$VENV/bin/python" "$REPO_DIR/fetch_prices.py" "$REPO_DIR"
  git add prices.json
  if git diff --cached --quiet; then
    echo "No change to prices.json"
  else
    git commit --quiet -m "prices $(date +%F)"
    git push --quiet
    echo "Pushed"
  fi
} >>"$LOG" 2>&1
