# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo


"""A Mail/HTTPS client."""

import gettext
import locale
import logging
import sys
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from signal import SIG_DFL, SIGINT, signal

import gi

gi.require_versions({"Gdk": "4.0", "Gtk": "4.0", "Adw": "1"})
from gi.repository import GLib

from ._config import APP_ID, LOCALEDIR, PKGDATADIR, PREFIX, PROFILE, VERSION
from ._notifier import Notifier
from ._property import Property
from .core import client

signal(SIGINT, SIG_DFL)

if sys.platform.startswith("linux"):
    locale.bindtextdomain("openemail", LOCALEDIR)
    locale.textdomain("openemail")

gettext.install("openemail", LOCALEDIR)

log_path = Path(GLib.get_user_state_dir(), "openemail.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s: %(name)s:%(lineno)d %(message)s",
    handlers=(
        StreamHandler(),
        RotatingFileHandler(log_path, maxBytes=1_000_000),
    ),
)

client.on_offline = lambda offline: Notifier().set_property("offline", offline)

__all__ = (
    "APP_ID",
    "LOCALEDIR",
    "PKGDATADIR",
    "PREFIX",
    "PROFILE",
    "VERSION",
    "Notifier",
    "Property",
)
