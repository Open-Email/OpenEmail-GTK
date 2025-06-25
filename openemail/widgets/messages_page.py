# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any, cast

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from openemail import PREFIX, mail
from openemail.dict_store import DictStore
from openemail.mail import Message, empty_trash, settings

from .compose_dialog import ComposeDialog  # noqa: TC001
from .content_page import ContentPage  # noqa: TC001
from .message_view import MessageView  # noqa: TC001


class _MessagesPage(Adw.NavigationPage):
    def __init__(self, model: Gio.ListModel, /, *, title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        bld = Gtk.Builder.new_from_resource(f"{PREFIX}/gtk/messages-page.ui")

        self.trashed = cast("Gtk.BoolFilter", bld.get_object("trashed"))
        settings.connect("changed::trashed-messages", self._on_trash_changed)
        cast("Gtk.SortListModel", bld.get_object("sort_model")).props.model = model

        self.compose_dialog = cast("ComposeDialog", bld.get_object("compose_dialog"))
        self.message_view = cast("MessageView", bld.get_object("message_view"))
        self.message_view.reply_button.connect(
            "clicked",
            lambda *_: self.compose_dialog.present_reply(message, self)
            if (message := self.message_view.message)
            else None,
        )

        self.content = cast("ContentPage", bld.get_object("content"))
        self.content.title = self.props.title = title
        self.content.model.connect("notify::selected", self._on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/message-row.ui"
        )

        self.props.child = self.content

    def _on_trash_changed(self, _obj: Any, _key: Any) -> None:
        m.autoselect = (m := self.content.model.props).selected != GLib.MAXUINT
        self.trashed.changed(Gtk.FilterChange.DIFFERENT)
        m.autoselect = False

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        self.message_view.message = (message := selection.props.selected_item)
        if not isinstance(message, Message):
            return

        message.mark_read()
        self.content.split_view.props.show_content = True


class _FolderPage(_MessagesPage):
    def __init__(self, folder: DictStore, /, **kwargs: Any) -> None:
        super().__init__(folder, **kwargs)

        bld = Gtk.Builder.new_from_resource(f"{PREFIX}/gtk/messages-page.ui")

        self.content.toolbar_button = cast("Gtk.Button", bld.get_object("toolbar_new"))
        self.content.empty_page = cast("Adw.StatusPage", bld.get_object("no_messages"))
        self.content.model.bind_property("selected-item", self.message_view, "message")

        for button in (
            self.content.toolbar_button,
            cast("Gtk.Button", bld.get_object("new_button")),
        ):
            button.connect("clicked", lambda *_: self.compose_dialog.present_new(self))

        folder.bind_property(
            "updating",
            self.content,
            "loading",
            GObject.BindingFlags.SYNC_CREATE,
        )


class InboxPage(_FolderPage):
    """A navigation page displaying the user's inbox."""

    __gtype_name__ = "InboxPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(mail.inbox, title=_("Inbox"), **kwargs)


class OutboxPage(_FolderPage):
    """A navigation page displaying the user's outbox."""

    __gtype_name__ = "OutboxPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(mail.outbox, title=_("Outbox"), **kwargs)


class DraftsPage(_MessagesPage):
    """A navigation page displaying the user's drafts."""

    __gtype_name__ = "DraftsPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(mail.drafts, title=_("Drafts"), **kwargs)

        bld = Gtk.Builder.new_from_resource(f"{PREFIX}/gtk/messages-page.ui")

        self.content.model.props.can_unselect = True

        delete_dialog = cast("Adw.AlertDialog", bld.get_object("delete_dialog"))
        delete_dialog.connect("response::delete", lambda *_: mail.drafts.delete_all())

        delete_button = cast("Gtk.Button", bld.get_object("delete_button"))
        delete_button.connect("clicked", lambda *_: delete_dialog.present(self))
        self.content.toolbar_button = delete_button

        self.content.empty_page = cast("Adw.StatusPage", bld.get_object("no_drafts"))
        self.content.model.bind_property(
            "n-items",
            delete_button,
            "sensitive",
            GObject.BindingFlags.SYNC_CREATE,
        )

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not isinstance(message := selection.props.selected_item, Message):
            return

        selection.unselect_all()
        self.compose_dialog.present_message(message, self)


class TrashPage(_MessagesPage):
    """A navigation page displaying the user's trash folder."""

    __gtype_name__ = "TrashPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            Gtk.FlattenListModel.new(folders := Gio.ListStore.new(Gio.ListModel)),
            title=_("Trash"),
            **kwargs,
        )

        bld = Gtk.Builder.new_from_resource(f"{PREFIX}/gtk/messages-page.ui")

        self.trashed.props.invert = False

        folders.append(mail.broadcasts)
        folders.append(mail.inbox)

        empty_dialog = cast("Adw.AlertDialog", bld.get_object("empty_dialog"))
        empty_dialog.connect("response::empty", lambda *_: empty_trash())

        empty_button = cast("Gtk.Button", bld.get_object("empty_button"))
        empty_button.connect("clicked", lambda *_: empty_dialog.present(self))
        self.content.toolbar_button = empty_button

        self.content.empty_page = cast("Adw.StatusPage", bld.get_object("empty_trash"))
        self.content.model.bind_property("selected-item", self.message_view, "message")
        self.content.model.bind_property(
            "n-items",
            empty_button,
            "sensitive",
            GObject.BindingFlags.SYNC_CREATE,
        )

        def set_loading(*_args: Any) -> None:
            self.content.loading = mail.inbox.updating or mail.broadcasts.updating

        mail.inbox.connect("notify::updating", set_loading)
        mail.broadcasts.connect("notify::updating", set_loading)


class BroadcastsPage(_FolderPage):
    """A navigation page displaying the user's broadcasts folder."""

    __gtype_name__ = "BroadcastsPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(mail.broadcasts, title=_("Public"), **kwargs)
