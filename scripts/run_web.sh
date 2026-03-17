#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../src"
streamlit run intelligence/web/app.py "$@"
