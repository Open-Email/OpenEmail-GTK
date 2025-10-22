# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import asyncio
from collections.abc import Callable
from http.client import HTTPResponse, InvalidURL
from logging import getLogger
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import crypto, urls
from .model import Address, User

MAX_AGENTS = 3

user = User()
on_offline: Callable[[bool], Any] | None = None

logger = getLogger(__name__)


async def request(
    url: str,
    *,
    auth: bool = False,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    max_length: int | None = None,
) -> HTTPResponse | None:
    """Make an HTTPS request, handling errors and authentication."""
    headers = headers or {}
    headers["User-Agent"] = "Mozilla/5.0"

    try:
        split = urlsplit(url)
        if split.scheme != "https":
            return None

        if auth:
            if not (agent := split.hostname):
                return None

            headers.update(
                {"Authorization": crypto.get_nonce(agent, user.signing_keys)}
            )

        response = await asyncio.to_thread(
            urlopen, Request(url, method=method, headers=headers, data=data)
        )
    except (InvalidURL, URLError, HTTPError, TimeoutError, ValueError) as error:
        if on_offline and isinstance(error, (URLError, TimeoutError)):
            on_offline(True)

        logger.debug(
            "%s, URL: %s, Method: %s, Auth: %s",
            error,
            url,
            method or ("POST" if data else "GET"),
            auth,
        )
        return None

    if max_length:
        try:
            length = int(response.headers.get("Content-Length", 0))
        except ValueError:
            return response

        if length > max_length:
            logger.debug("Content-Length for %s exceeds max_length", url)
            return None

    if on_offline:
        on_offline(False)

    return response


_agents = dict[str, tuple[str, ...]]()


async def get_agents(address: Address) -> tuple[str, ...]:
    """Get the first ≤3 responding mail agents for a given `address`."""
    if existing := _agents.get(address.host_part):
        return existing

    contents = None
    for location in (
        f"https://{address.host_part}/.well-known/mail.txt",
        f"https://mail.{address.host_part}/.well-known/mail.txt",
    ):
        if not (response := await request(location)):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        index = 1
        async for agent in (
            stripped
            for line in contents.split("\n")
            if (stripped := line.strip()) and (not stripped.startswith("#"))
            if await request(urls.Mail(stripped, address).host, method="HEAD")
        ):
            if index > MAX_AGENTS:
                break

            _agents[address.host_part] = (*_agents.get(address.host_part, ()), agent)
            index += 1

        break

    return _agents.get(address.host_part, (f"mail.{address.host_part}",))
