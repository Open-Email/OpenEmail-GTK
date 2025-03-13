# form.py
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


from enum import Enum
from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail.core.user import Address


class MailFormField(Enum):
    """A type of field in a form."""

    PLAIN = 1
    ADDRESS = 2
    ADDRESS_LIST = 3


class MailForm(GObject.Object):
    """A split view for content and details."""

    __gtype_name__ = "MailForm"

    form = GObject.Property(type=Gtk.Widget)
    submit = GObject.Property(type=GObject.Object)

    invalid: set[Gtk.Editable | Gtk.TextBuffer]

    _fields: dict[MailFormField, Gtk.StringList]

    @GObject.Property(type=Gtk.StringList)
    def plain(self) -> Gtk.StringList | None:
        """Get the plain, text-only fields of the form."""
        return self._fields.get(MailFormField.PLAIN)

    @plain.setter
    def plain(self, fields: Gtk.StringList) -> None:
        self.__assign_fields(MailFormField.PLAIN, fields)

    @GObject.Property(type=Gtk.StringList)
    def addresses(self) -> Gtk.StringList | None:
        """Get fields of the form for addresses."""
        return self._fields.get(MailFormField.ADDRESS)

    @addresses.setter
    def addresses(self, fields: Gtk.StringList) -> None:
        self.__assign_fields(MailFormField.ADDRESS, fields)

    @GObject.Property(type=Gtk.StringList)
    def address_lists(self) -> Gtk.StringList | None:
        """Get fields of the form for comma-separated lists of addresses."""
        return self._fields.get(MailFormField.ADDRESS_LIST)

    @address_lists.setter
    def address_lists(self, fields: Gtk.StringList) -> None:
        self.__assign_fields(MailFormField.ADDRESS_LIST, fields)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fields = {}

    def reset(self) -> None:
        """Reset the state of the form.

        Useful for reusable widgets after submission.
        """
        for fields in self._fields.values():
            for field in fields:
                try:
                    getattr(self.form, field.get_string()).set_text("")
                except AttributeError:
                    continue

    def __assign_fields(self, type: MailFormField, fields: Gtk.StringList) -> None:
        self._fields[type] = fields

        if self.form.get_realized():
            self.__setup()
            return

        self.form.connect("realize", self.__setup)

    def __setup(self, *_args: Any) -> None:
        try:
            self.form.disconnect_by_func(self.__setup)
        except TypeError:
            pass

        self.invalid = set()

        for type, fields in self._fields.items():
            for field in fields:
                try:
                    field = getattr(self.form, field.get_string())
                except AttributeError:
                    continue

                field.connect("changed", self.__validate, type)
                self.__validate(field, type)

        self.__verify()

    def __validate(
        self,
        field: Gtk.Editable | Gtk.TextBuffer,
        type: MailFormField,
    ) -> None:
        text = (
            field.get_text()
            if isinstance(field, Gtk.Editable)
            else field.get_text(
                field.get_start_iter(),
                field.get_end_iter(),
                False,
            )
        )

        match type:
            case MailFormField.PLAIN:
                (self.__valid if text else self.__invalid)(field)

            case MailFormField.ADDRESS:
                try:
                    Address(text)
                except ValueError:
                    self.__invalid(field)
                    return

                self.__valid(field)

            case MailFormField.ADDRESS_LIST:
                if not (
                    addresses := tuple(
                        stripped
                        for address in text.split(",")
                        if (stripped := address.strip())
                    )
                ):
                    self.__valid(field)
                    return

                for address in addresses:
                    try:
                        Address(address)
                    except ValueError:
                        self.__invalid(field)
                        return

                self.__valid(field)

    def __verify(self) -> None:
        if isinstance(self.submit, Adw.AlertDialog):
            if not (default := self.submit.get_default_response()):
                return

            self.submit.set_response_enabled(default, not self.invalid)
            return

        if isinstance(self.submit, Gtk.Widget):
            self.submit.set_sensitive(not self.invalid)

    def __valid(self, editable: Gtk.Editable | Gtk.TextBuffer) -> None:
        self.invalid.discard(editable)
        self.__verify()

    def __invalid(self, editable: Gtk.Editable | Gtk.TextBuffer) -> None:
        self.invalid.add(editable)
        self.__verify()
