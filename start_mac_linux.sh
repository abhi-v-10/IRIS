#!/usr/bin/env bash
# Invoice & Receipt Intelligence System - start script for macOS / Linux
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is required (https://www.python.org/downloads/)."; exit 1
fi
if [ ! -d venv ]; then
  echo "First run: creating a virtual environment and installing packages..."
  "$PY" -m venv venv
  venv/bin/python -m pip install --upgrade pip >/dev/null
  venv/bin/python -m pip install -r requirements.txt
fi
command -v tesseract >/dev/null 2>&1 || echo "WARNING: Tesseract OCR not found. Install it: sudo apt install tesseract-ocr  (or: brew install tesseract)"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:5000) || (command -v open >/dev/null && open http://127.0.0.1:5000) ) >/dev/null 2>&1 &
exec venv/bin/python run.py "$@"
