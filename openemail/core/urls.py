# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

# ruff: noqa: D101

from .model import Address


class Home:
    def __init__(self, agent: str, address: Address):
        self.home = f"https://{agent}/home/{address.host_part}/{address.local_part}"
        self.links = f"{self.home}/links"
        self.profile = f"{self.home}/profile"
        self.image = f"{self.home}/image"
        self.messages = f"{self.home}/messages"
        self.notifications = f"{self.home}/notifications"


class Message(Home):
    def __init__(self, agent: str, address: Address, ident: str):
        super().__init__(agent, address)
        self.message = f"{self.messages}/{ident}"


class Mail:
    def __init__(self, agent: str, address: Address):
        self.host = f"https://{agent}/mail/{address.host_part}"
        self.mail = f"{self.host}/{address.local_part}"
        self.profile = f"{self.mail}/profile"
        self.image = f"{self.mail}/image"
        self.messages = f"{self.mail}/messages"


class Account:
    def __init__(self, agent: str, address: Address):
        self.account = (
            f"https://{agent}/account/{address.host_part}/{address.local_part}"
        )


class Link:
    def __init__(self, agent: str, address: Address, link: str):
        self.home = f"{Home(agent, address).home}/links/{link}"
        self.mail = f"{Mail(agent, address).mail}/link/{link}"
        self.messages = f"{self.mail}/messages"
        self.notifications = f"{self.mail}/notifications"
