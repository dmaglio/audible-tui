from pathlib import Path
import os

LOCALE = os.environ.get("AUDIBLE_TUI_LOCALE", "it")  # mercato: it, de, fr, uk, us…
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "audible-tui"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "audible-tui"
AUTH_FILE = CONFIG_DIR / "auth.json"
BOOKS_DIR = Path(os.environ.get("AUDIBLE_TUI_BOOKS", Path.home() / "Audiolibri"))
