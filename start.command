#!/usr/bin/env bash
# ============================================================
# LORIS — Doppio Clic per Avviare (macOS Launcher)
# ============================================================
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

chmod +x ./run_app.sh
./run_app.sh --browser
