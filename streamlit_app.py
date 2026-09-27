"""Thin launcher so `streamlit run streamlit_app.py` works without setting
PYTHONPATH by hand (Streamlit puts only this file's own directory on
sys.path, not `src/`, so the package import is wired up here instead)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kpi_dashboard.app import render  # noqa: E402

render()
