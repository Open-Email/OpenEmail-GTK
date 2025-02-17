# auth.py
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

from urllib import request
from urllib.error import HTTPError, URLError

from openemail.crypto import SIGNING_ALGORITHM, Key, random_string, sign_data
from openemail.network import HEADERS, get_agents
from openemail.user import User


def get_nonce(host: str, public_key: Key, private_key: Key) -> str:
    """Returns a nonce used for authentication for the given agent `host` and `private_key`."""
    return "SOTN " + "; ".join(
        (
            f"value={(value := random_string(30))}",
            f"host={host}",
            f"algorithm={SIGNING_ALGORITHM}",
            f"signature={sign_data(private_key, f'{host}{value}'.encode('utf-8'))}",
            f"key={public_key.string}",
        )
    )


def try_auth(user: User) -> bool:
    """Returns whether authentication was successful for the given `user`."""
    for agent in get_agents(user.address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/home/{user.address.host_part}/{user.address.local_part}",
                    headers=HEADERS
                    | {
                        "Authorization": get_nonce(
                            agent,
                            user.public_signing_key,
                            user.private_signing_key,
                        )
                    },
                    method="HEAD",
                ),
            ):
                return True
        except (HTTPError, URLError, ValueError, TimeoutError):
            continue

    return False
