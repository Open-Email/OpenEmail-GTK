# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import sha256
from random import choice
from secrets import token_bytes
from typing import NamedTuple, Type

from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
    crypto_aead_xchacha20poly1305_ietf_NPUBBYTES,
    crypto_scalarmult_base,
)
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey
from nacl.utils import random

ANONYMOUS_ENCRYPTION_CIPHER = "curve25519xsalsa20poly1305"
CHECKSUM_ALGORITHM = "sha256"
SIGNING_ALGORITHM = "ed25519"
SYMMETRIC_CIPHER = "xchacha20poly1305"


class Key(NamedTuple):
    """A cryptographic key using `algorithm` with the value of `data`, and an optional `id`."""

    data: bytes
    algorithm: str = SIGNING_ALGORITHM
    key_id: str | None = None

    def __bytes__(self) -> bytes:
        return self.data

    def __str__(self) -> str:
        return b64encode(bytes(self)).decode("utf-8")


@dataclass(slots=True)
class KeyPair[T: KeyPair]:
    """A public-private keypair."""

    private: Key
    public: Key

    @classmethod
    def from_b64(cls: Type[T], b64: str) -> T:
        """Get the keypair for a given Base64-encoded string."""
        bytes = b64decode(b64.encode("utf-8"))
        match len(bytes):
            case 32:
                return cls(Key(bytes), Key(crypto_scalarmult_base(bytes)))
            case 64:
                return cls(Key(bytes[:32]), Key(bytes[32:]))
            case length:
                raise ValueError(f"Invalid key length of {length}")

    @classmethod
    def for_encryption(cls: Type[T]) -> T:
        """Generate a new keypair used for encryption."""
        return cls(
            Key(bytes(key := PrivateKey.generate())),
            Key(bytes(key.public_key), key_id=random_string(4)),
        )

    @classmethod
    def for_signing(cls: Type[T]) -> T:
        """Generate a new keypair used for signing."""
        return cls(Key(bytes(key := SigningKey.generate())), Key(bytes(key.verify_key)))

    def __bytes__(self) -> bytes:
        return bytes(self.private) + bytes(self.public)

    def __str__(self) -> str:
        return b64encode(bytes(self)).decode("utf-8")


def sign_data(private_key: Key, data: bytes) -> str:
    """Get a Base64-encoded version of given `data` signed using the provided `private_key`."""
    try:
        return b64encode(
            SigningKey(bytes(private_key)).sign(data).signature,
        ).decode("utf-8")
    except CryptoError as error:
        raise ValueError("Unable to sign data") from error


def random_bytes(length: int) -> bytes:
    """Generate a byte sequence of a given `length`."""
    return token_bytes(length)


def random_string(length: int) -> str:
    """Generate a random string of a given `length` from characters 0..9, A..Z, and a..z."""
    return "".join(
        choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        for _ in range(length)
    )


def get_nonce(agent: str, keys: KeyPair) -> str:
    """Get an authentication nonce for the given `agent` and `keys`."""
    try:
        return "SOTN " + "; ".join(
            (
                f"value={(value := random_string(30))}",
                f"host={agent}",
                f"algorithm={SIGNING_ALGORITHM}",
                f"signature={sign_data(keys.private, f'{agent}{value}'.encode('utf-8'))}",
                f"key={keys.public}",
            )
        )
    except ValueError as error:
        raise ValueError("Unable to get authentication nonce") from error


def decrypt_anonymous(cipher_text: str, private_key: Key) -> bytes:
    """Decrypt `cipher_text` using the provided `private_key`."""
    try:
        data = b64decode(cipher_text)
    except ValueError as error:
        raise ValueError("Invalid cipher text") from error

    try:
        return SealedBox(PrivateKey(bytes(private_key))).decrypt(data)
    except CryptoError as error:
        raise ValueError("Unable to decrypt cipher text") from error


def encrypt_anonymous(data: bytes, public_key: Key) -> bytes:
    """Encrypt `data` using the provided `public_key`."""
    try:
        return SealedBox(PublicKey(bytes(public_key))).encrypt(data)
    except CryptoError as error:
        raise ValueError("Unable to encrypt data") from error


def decrypt_xchacha20poly1305(data: bytes, access_key: bytes) -> bytes:
    """Decrypt `data` using `access_key`."""
    try:
        return crypto_aead_xchacha20poly1305_ietf_decrypt(
            data[crypto_aead_xchacha20poly1305_ietf_NPUBBYTES:],
            None,
            data[:crypto_aead_xchacha20poly1305_ietf_NPUBBYTES],
            access_key,
        )
    except CryptoError as error:
        raise ValueError("Unable to decrypt data") from error


def encrypt_xchacha20poly1305(data: bytes, access_key: bytes) -> bytes:
    """Encrypt `data` using `access_key`."""
    try:
        nonce = random(crypto_aead_xchacha20poly1305_ietf_NPUBBYTES)
        return nonce + crypto_aead_xchacha20poly1305_ietf_encrypt(
            data, None, nonce, access_key
        )
    except CryptoError as error:
        raise ValueError("Unable to encrypt data") from error


def fingerprint(public_key: Key) -> str:
    """Get a fingerprint for `public_key`."""
    return sha256(bytes(public_key)).hexdigest()
