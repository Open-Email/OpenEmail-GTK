"""The core Mail/HTTPS client."""

from os import getenv
from pathlib import Path

from .model import User

data_dir = Path(getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"), "openemail")
user = User()
