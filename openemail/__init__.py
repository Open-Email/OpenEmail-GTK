# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

# ruff: noqa: F401

"""A Mail/HTTPS client."""

import gettext
import locale
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

import gi

from .configuration import APP_ID, LOCALEDIR, PKGDATADIR, PREFIX, PROFILE, VERSION
from .core.client import WriteError, user
from .core.crypto import KeyPair
from .core.model import Address

signal.signal(signal.SIGINT, signal.SIG_DFL)

gi.require_versions({"Gdk": "4.0", "Gtk": "4.0", "Adw": "1"})

if sys.platform.startswith("linux"):
    locale.bindtextdomain("openemail", LOCALEDIR)
    locale.textdomain("openemail")

gettext.install("openemail", LOCALEDIR)

from .account import delete as delete_account
from .account import log_out, register, try_auth
from .asyncio import create_task
from .message import Attachment, IncomingAttachment, Message, OutgoingAttachment
from .message import send as send_message
from .notifier import Notifier
from .profile import Profile, ProfileCategory, ProfileField
from .profile import delete_image as delete_profile_image
from .profile import refresh as refresh_profile
from .profile import update as update_profile
from .profile import update_image as update_profile_image
from .property import Property
from .store import (
    ADDRESS_SPLIT_PATTERN,
    DictStore,
    MessageStore,
    People,
    ProfileStore,
    address_book,
    broadcasts,
    contact_requests,
    drafts,
    empty_trash,
    inbox,
    log_path,
    outbox,
    profiles,
    secret_service,
    settings,
    settings_add,
    settings_discard,
    state_settings,
    sync,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s: %(name)s:%(lineno)d %(message)s",
    handlers=(
        (
            logging.StreamHandler(),
            RotatingFileHandler(log_path, maxBytes=1_000_000),
        )
    ),
)
