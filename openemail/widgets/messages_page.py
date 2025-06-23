# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from openemail import PREFIX, mail, settings
from openemail.dict_store import DictStore
from openemail.mail import Message, empty_trash

from .compose_dialog import ComposeDialog
from .content_page import ContentPage
from .message_view import MessageView


class _MessagesPage(Adw.NavigationPage):
    compose_dialog: ComposeDialog
    message_view: MessageView
    content: ContentPage

    def __init__(self, model: Gio.ListModel, *, title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.compose_dialog = ComposeDialog()
        self.message_view = MessageView()

        self.content = ContentPage(
            title=title,
            details=self.message_view,
            model=Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    Gtk.FilterListModel.new(
                        model,
                        (
                            search_filter := Gtk.CustomFilter.new(
                                lambda item: (
                                    (lowered := self.content.search_text.lower())
                                    in item.name.lower()
                                    or lowered in item.subject.lower()
                                    or lowered in item.body.lower()
                                )
                                if self.content.search_text
                                else True
                            )
                        ),
                    ),
                    Gtk.CustomSorter.new(lambda a, b, _: int(b > a) - int(b < a)),
                ),
            ),
            factory=Gtk.BuilderListItemFactory.new_from_resource(
                None, f"{PREFIX}/gtk/message-row.ui"
            ),
        )

        self.content.connect(
            "notify::search-text",
            lambda *_: search_filter.changed(Gtk.FilterChange.DIFFERENT),
        )

        self.props.child = self.content
        self.props.title = title

    def on_trash_changed(self, _obj: Any, _key: Any, trashed: Gtk.CustomFilter) -> None:
        selection = self.content.model.props.selected

        if selection != GLib.MAXUINT:
            self.content.model.props.autoselect = True

        trashed.changed(Gtk.FilterChange.DIFFERENT)
        self.content.model.props.autoselect = False


class _SplitPage(_MessagesPage):
    def __init__(self, model: Gio.ListModel, **kwargs: Any) -> None:
        super().__init__(model, **kwargs)

        def on_selected(selection: Gtk.SingleSelection, *_args: Any) -> None:
            if not isinstance(selected := selection.props.selected_item, Message):
                return

            selected.mark_read()
            self.content.split_view.props.show_content = True

        self.content.model.connect("notify::selected", on_selected)
        self.content.model.bind_property("selected-item", self.message_view, "message")


class _FolderPage(_SplitPage):
    def __init__(self, folder: DictStore, **kwargs: Any) -> None:
        super().__init__(
            Gtk.FilterListModel.new(
                folder, trashed := Gtk.CustomFilter.new(lambda item: not item.trashed)
            ),
            **kwargs,
        )

        settings.connect("changed::trashed-messages", self.on_trash_changed, trashed)

        self.content.empty_page = Adw.StatusPage(
            icon_name="mailbox-symbolic",
            title=_("No Messages"),
            description=_("Select another folder or start a conversation"),
            child=(
                new_message := Gtk.Button(
                    halign=Gtk.Align.CENTER,
                    label=_("New Message"),
                )
            ),
        )

        new_message.add_css_class("pill")
        new_message.connect("clicked", lambda *_: self.compose_dialog.present_new(self))

        self.content.empty_page.add_css_class("compact")

        self.content.toolbar_button = Gtk.Button(
            icon_name="mail-message-new-symbolic",
            tooltip_text=_("New Message"),
        )

        controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>n"),
                Gtk.ShortcutAction.parse_string("activate"),
            )
        )

        self.content.toolbar_button.add_controller(controller)
        self.content.toolbar_button.connect(
            "clicked", lambda *_: self.compose_dialog.present_new(self)
        )

        self.message_view.reply_button.connect(
            "clicked",
            lambda *_: self.compose_dialog.present_reply(
                self.message_view.message, self
            )
            if self.message_view.message
            else self.compose_dialog.present_new(self),
        )

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

        def on_selected(selection: Gtk.SingleSelection, *_args: Any) -> None:
            if not (isinstance(message := selection.props.selected_item, Message)):
                return

            selection.unselect_all()
            self.compose_dialog.present_message(message, self)

        self.content.model.connect("notify::selected", on_selected)

        delete_dialog = Adw.AlertDialog(
            heading=_("Delete Drafts?"),
            body=_("All drafts will be permanently deleted"),
            default_response="delete",
        )

        delete_dialog.add_response("close", _("Cancel"))
        delete_dialog.add_response("delete", _("Delete All"))
        delete_dialog.set_response_appearance(
            "delete", Adw.ResponseAppearance.DESTRUCTIVE
        )

        delete_dialog.connect("response::delete", lambda *_: mail.drafts.delete_all())

        self.content.toolbar_button = Gtk.Button(
            icon_name="fire-symbolic",
            tooltip_text=_("Delete All"),
        )

        self.content.toolbar_button.connect(
            "clicked", lambda *_: delete_dialog.present(self)
        )

        self.content.empty_page = Adw.StatusPage(
            icon_name="drafts-symbolic",
            title=_("No Drafts"),
            description=_("New unsent messages will appear here"),
        )

        self.content.empty_page.add_css_class("compact")


class TrashPage(_SplitPage):
    """A navigation page displaying the user's trash folder."""

    __gtype_name__ = "TrashPage"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            Gtk.FilterListModel.new(
                Gtk.FlattenListModel.new(folders := Gio.ListStore.new(Gio.ListModel)),
                trashed := Gtk.CustomFilter.new(lambda item: item.trashed),
            ),
            title=_("Trash"),
            **kwargs,
        )

        folders.append(mail.broadcasts)
        folders.append(mail.inbox)

        settings.connect("changed::trashed-messages", self.on_trash_changed, trashed)

        self.content.empty_page = Adw.StatusPage(
            icon_name="trash-symbolic",
            title=_("Trash is Empty"),
        )

        self.content.empty_page.add_css_class("compact")

        empty_dialog = Adw.AlertDialog(
            heading=_("Empty Trash?"),
            body=_("All items in the trash will be permanently deleted"),
            default_response="empty",
        )

        empty_dialog.add_response("close", _("Cancel"))
        empty_dialog.add_response("empty", _("Empty Trash"))
        empty_dialog.set_response_appearance(
            "empty", Adw.ResponseAppearance.DESTRUCTIVE
        )

        empty_dialog.connect("response::empty", lambda *_: empty_trash())

        self.content.toolbar_button = Gtk.Button(
            icon_name="empty-trash-symbolic",
            tooltip_text=_("Empty Trash"),
        )

        self.content.toolbar_button.connect(
            "clicked", lambda *_: empty_dialog.present(self)
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
