# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Gio, GObject


class Property[T](GObject.Property):
    """A more convenient and correctly typed GObject property."""

    def __init__(self, type: type[T], /, *, default: T | None = None):  # noqa: A002
        super().__init__(
            type=type, default=default or (False if type is bool else default)
        )

    def __get__(self, instance: GObject.Object, klass: Any) -> T:  # noqa: ANN401
        return super().__get__(instance, klass)

    def __set__(self, instance: GObject.Object, value: T):
        super().__set__(instance, value)

    @staticmethod
    def bind(
        source: GObject.Object,
        source_property: str,
        target: GObject.Object,
        target_property: str | None = None,
        /,
        *,
        bidirectional: bool = False,
    ) -> GObject.Binding:
        """Create property bindings more conveniently.

        An empty `target_property` is assumed to be the same as `source_property`.
        """
        return source.bind_property(
            source_property,
            target,
            target_property or source_property,
            GObject.BindingFlags.SYNC_CREATE
            | (GObject.BindingFlags.BIDIRECTIONAL if bidirectional else 0),
        )

    @staticmethod
    def bind_setting(
        settings: Gio.Settings,
        key: str,
        target: GObject.Object,
        target_property: str | None = None,
        /,
    ):
        """Create setting bindings more conveniently.

        An empty `target_property` is assumed to be the same as `key`.
        """
        settings.bind(
            key, target, target_property or key, Gio.SettingsBindFlags.DEFAULT
        )
