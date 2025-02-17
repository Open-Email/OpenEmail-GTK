# crypto.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import random
from base64 import b64decode, b64encode
from typing import NamedTuple

from nacl.signing import SigningKey

SIGNING_ALGORITHM = "ed25519"


class Key(NamedTuple):
    """A cryptographic key using `algorithm` with the value of `bytes`, and an optional `id`."""

    bytes: bytes
    algorithm: str = SIGNING_ALGORITHM
    id: str | None = None

    @property
    def string(self) -> str:
        """Base64-encoded string representation of the key."""
        return b64encode(self.bytes).decode("utf-8")


def random_string(length: int) -> str:
    """Generates a random string of a given `length` from characters 0..9, A..Z, and a..z."""
    return "".join(
        random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        for _ in range(length)
    )


def sign_data(private_key: Key, data: bytes) -> str:
    """Returns a Base64-encoded version of given `data` signed using the provided `private_key`."""

    return b64encode(SigningKey(private_key.bytes).sign(data).signature).decode("utf-8")


def get_keys(b64: str) -> tuple[Key, Key]:
    """Returns the public-private key pair for a given Base64-encoded string."""

    bytes = b64decode(b64.encode("utf-8"))
    match len(bytes):
        case 32:
            return Key(SigningKey(bytes).verify_key.encode()), Key(bytes)
        case 64:
            return Key(bytes[32:]), Key(bytes[:32])
        case length:
            raise ValueError(f"Invalid key length of {length}.")
