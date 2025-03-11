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


from typing import Any, Literal

from gi.repository import Adw, GObject, Gtk

from openemail.core.user import Address


class MailForm(GObject.Object):
    """A split view for content and details."""

    __gtype_name__ = "MailForm"

    form = GObject.Property(type=Gtk.Widget)
    submit = GObject.Property(type=GObject.Object)

    invalid: set[Gtk.Editable | Gtk.TextBuffer]

    _fields: Gtk.StringList | None = None

    @GObject.Property(type=Gtk.StringList)
    def fields(self) -> Gtk.StringList | None:
        """Get the fields of the form."""
        return self._fields

    @fields.setter
    def fields(self, fields: Gtk.StringList) -> None:
        self._fields = fields

        if self.form.get_realized():
            self.__setup()
            return

        self.form.connect("realize", self.__setup)

    def __setup(self, *_args: Any) -> None:
        self.form.disconnect_by_func(self.__setup)
        self.invalid = set()

        type = None
        for index, field in enumerate(self.fields):
            field = field.get_string()

            if not (index % 2):
                type = field
                continue

            if not type:
                continue

            try:
                field = getattr(self.form, field)
            except AttributeError:
                continue

            field.connect("changed", self.__validate, type)
            self.__validate(field, type)

        self.__verify()

    def __validate(
        self,
        field: Gtk.Editable | Gtk.TextBuffer,
        type: Literal["plain", "address", "addresses"],
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
            case "plain":
                (self.__valid if text else self.__invalid)(field)

            case "address":
                try:
                    Address(text)
                except ValueError:
                    self.__invalid(field)
                    return

                self.__valid(field)

            case "addresses":
                for address in text.split(","):
                    if not (address := address.strip()):
                        continue

                    try:
                        Address(address.strip())
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
