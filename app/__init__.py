from pathlib import Path

try:
    VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
except OSError:
    VERSION = "0.0.0"
