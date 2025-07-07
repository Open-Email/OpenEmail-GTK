# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
import logging
import sys
from logging.handlers import RotatingFileHandler

import keyring
from gi.repository import Adw

from openemail import APP_ID, log_file, mail, secret_service, settings
from openemail.mail import Address, KeyPair

from .widgets.window import Window


class Application(Adw.Application):
    """The main application singleton class."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)

        if not (
            (address := settings.get_string("address"))
            and (keys := keyring.get_password(secret_service, address))
            and (keys := json.loads(keys))
            and (encryption_key := keys.get("privateEncryptionKey"))
            and (signing_key := keys.get("privateSigningKey"))
        ):
            return

        try:
            mail.user.address = Address(address)
            mail.user.encryption_keys = KeyPair.from_b64(encryption_key)
            mail.user.signing_keys = KeyPair.from_b64(signing_key)
        except ValueError:
            return

    def do_activate(self) -> None:
        """Raise the application's main window, creating it if necessary.

        Called when the application is activated.
        """
        (self.props.active_window or Window(application=self)).present()


def main() -> int:
    """Run the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(name)s:%(lineno)d %(message)s",
        handlers=(
            (
                logging.StreamHandler(),
                RotatingFileHandler(log_file, maxBytes=1_000_000),
            )
        ),
    )

    return Application().run(sys.argv)
