# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import json
from collections.abc import Generator
from datetime import datetime
from json import JSONDecodeError
from logging import getLogger
from shutil import rmtree

from . import data_dir
from .model import Address, DraftMessage

logger = getLogger(__name__)


def save(draft: DraftMessage):
    """Serialize and save a message to disk for future use.

    See `messages.send()` for other parameters,
    `load()` on how to retrieve it.
    """
    logger.debug("Saving draft…")
    messages_path = data_dir / "drafts"

    message_path = messages_path / f"{draft.ident}.json"
    message_path.parent.mkdir(parents=True, exist_ok=True)

    with message_path.open("w") as file:
        json.dump(
            (
                draft.date.isoformat(timespec="seconds"),
                draft.subject,
                draft.subject_id,
                list(map(str, draft.readers)),
                draft.body,
                draft.is_broadcast,
            ),
            file,
        )

    logger.debug("Draft saved as %s.json", draft.ident)


def load() -> Generator[DraftMessage]:
    """Load all drafts saved to disk.

    See `save()`.
    """
    logger.debug("Loading drafts…")
    if not (messages_path := data_dir / "drafts").is_dir():
        logger.debug("No drafts")
        return

    for path in messages_path.iterdir():
        try:
            with path.open("r") as file:
                fields = tuple(json.load(file))

        except (JSONDecodeError, ValueError):
            continue

        try:
            yield DraftMessage(
                ident=path.stem,
                date=datetime.fromisoformat(fields[0]),
                subject=fields[1],
                subject_id=fields[2],
                readers=[Address(r) for r in fields[3]],
                body=fields[4],
                broadcast=fields[5],
            )
        except (KeyError, ValueError):
            continue

    logger.debug("Loaded all drafts")


def delete(ident: str):
    """Delete the draft saved using `ident`.

    See `save()` and `load()`.
    """
    logger.debug("Deleting draft %s…", ident)

    try:
        (data_dir / "drafts" / f"{ident}.json").unlink()
    except FileNotFoundError as error:
        logger.debug("Failed to delete draft %s: %s", ident, error)
        return

    logger.debug("Deleted draft %s", ident)


def delete_all():
    """Delete all drafts saved using `save()`."""
    logger.debug("Deleting all drafts…")
    rmtree(data_dir / "drafts", ignore_errors=True)
    logger.debug("Deleted all drafts")
