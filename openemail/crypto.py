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

from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_NPUBBYTES,
    crypto_scalarmult_base,
)
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, SealedBox
from nacl.signing import SigningKey

SIGNING_ALGORITHM = "ed25519"


class Key(NamedTuple):
    """A cryptographic key using `algorithm` with the value of `bytes`, and an optional `id`."""

    data: bytes
    algorithm: str = SIGNING_ALGORITHM
    id: str | None = None

    def __str__(self) -> str:
        return b64encode(self.data).decode("utf-8")

    def __bytes__(self) -> bytes:
        return self.data


def get_keys(b64: str) -> tuple[Key, Key]:
    """Get the public-private key pair for a given Base64-encoded string."""
    bytes = b64decode(b64.encode("utf-8"))
    match len(bytes):
        case 32:
            return Key(crypto_scalarmult_base(bytes)), Key(bytes)
        case 64:
            return Key(bytes[32:]), Key(bytes[:32])
        case length:
            raise ValueError(f"Invalid key length of {length}.")


def sign_data(private_key: Key, data: bytes) -> str:
    """Get a Base64-encoded version of given `data` signed using the provided `private_key`."""
    return b64encode(
        SigningKey(
            bytes(private_key),
        )
        .sign(data)
        .signature
    ).decode("utf-8")


def random_string(length: int) -> str:
    """Generate a random string of a given `length` from characters 0..9, A..Z, and a..z."""
    return "".join(
        random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        for _ in range(length)
    )


def get_nonce(host: str, public_key: Key, private_key: Key) -> str:
    """Get a nonce used for authentication for the given agent `host` and `private_key`."""
    return "SOTN " + "; ".join(
        (
            f"value={(value := random_string(30))}",
            f"host={host}",
            f"algorithm={SIGNING_ALGORITHM}",
            f"signature={sign_data(private_key, f'{host}{value}'.encode('utf-8'))}",
            f"key={public_key}",
        )
    )


def decrypt_anonymous(cipher_text: str, private_key: Key, public_key: Key) -> bytes:
    """Attempt to decrypt `cipher_text` using the provided keys."""
    try:
        data = b64decode(cipher_text)
    except ValueError as error:
        raise ValueError("Invalid cipher text.") from error

    try:
        return SealedBox(PrivateKey(bytes(private_key))).decrypt(data)
    except CryptoError as error:
        raise ValueError("Unable to decrypt cipher text.") from error


def decrypt_xchacha20poly1305(data: bytes, access_key: bytes) -> bytes:
    """Attempt to decrypt `data` using `access_key`."""
    try:
        return crypto_aead_xchacha20poly1305_ietf_decrypt(
            data[crypto_aead_xchacha20poly1305_ietf_NPUBBYTES:],
            None,
            data[:crypto_aead_xchacha20poly1305_ietf_NPUBBYTES],
            access_key,
        )
    except CryptoError as error:
        raise ValueError("Unable to decrypt data.") from error
