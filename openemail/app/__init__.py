# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

"""A Mail/HTTPS client."""

import gi

gi.require_versions({"Gdk": "4.0", "Gtk": "4.0", "Adw": "1"})

from ._asyncio import create_task
from ._notifier import Notifier

__all__ = ("Notifier", "create_task")

APP_ID: str
VERSION: str
PREFIX: str
PROFILE: str
