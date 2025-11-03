"""The core Mail/HTTPS client."""

from os import getenv
from pathlib import Path

data_dir = Path(getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"), "openemail")
cache_dir = Path(getenv("XDG_CACHE_HOME", Path.home() / ".cache"), "openemail")
