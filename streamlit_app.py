"""Entry point for hosting services that look for streamlit_app.py by default. The app itself is app/FairSend.py."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "app" / "FairSend.py"), run_name="__main__")
