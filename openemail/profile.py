# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from collections.abc import Iterator
from typing import Any, Self

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from . import Notifier, Property, tasks
from .core import client, contacts, model, profile
from .core.crypto import KeyPair
from .core.model import Address, User, WriteError

MAX_IMAGE_DIMENSIONS = 800


class ProfileField(GObject.Object):
    """A field for information on a user."""

    ident = Property(str)
    name = Property(str)

    def __init__(self, ident: str, name: str, **kwargs: Any):
        super().__init__(**kwargs)

        self.ident = ident
        self.name = name


class ProfileCategory(GObject.Object, Gio.ListModel):  # pyright: ignore[reportIncompatibleMethodOverride]
    """A category of profile fields."""

    ident = Property(str)
    name = Property(str)

    def __init__(
        self,
        ident: str,
        name: str,
        fields: dict[str, str],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)

        self.ident = ident
        self.name = name
        self._fields = tuple(ProfileField(K, V) for K, V in fields.items())

    def __iter__(self) -> Iterator[ProfileField]:
        return super().__iter__()  # pyright: ignore[reportReturnType]

    def do_get_item(self, position: int) -> ProfileField:
        """Get the item at `position`."""
        return self._fields[position]

    def do_get_item_type(self) -> type[ProfileField]:
        """Get the type of the items in `self`."""
        return ProfileField

    def do_get_n_items(self) -> int:
        """Get the number of items in `self`."""
        return len(self._fields)


class Profile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = __qualname__

    updating = Property(bool)

    contact_request = Property(bool)
    has_name = Property(bool)
    has_image = Property(bool)

    categories = (
        ProfileCategory(
            "general",
            _("General"),
            {
                "status": _("Status"),
                "about": _("About"),
            },
        ),
        ProfileCategory(
            "personal",
            _("Personal"),
            {
                "gender": _("Gender"),
                "relationship-status": _("Relationship Status"),
                "birthday": _("Birthday"),
                "education": _("Education"),
                "languages": _("Languages"),
                "places-lived": _("Places Lived"),
                "notes": _("Notes"),
            },
        ),
        ProfileCategory(
            "work",
            _("Work"),
            {
                "work": _("Work"),
                "organization": _("Organization"),
                "department": _("Department"),
                "job-title": _("Job Title"),
            },
        ),
        ProfileCategory(
            "interests",
            _("Interests"),
            {
                "interests": _("Interests"),
                "books": _("Books"),
                "movies": _("Movies"),
                "music": _("Music"),
                "sports": _("Sports"),
            },
        ),
        ProfileCategory(
            "contacts",
            _("Contact"),
            {
                "website": _("Website"),
                "location": _("Location"),
                "mailing-address": _("Mailing Address"),
                "phone": _("Phone"),
                "streams": _("Topics"),
            },
        ),
        ProfileCategory(
            "configuration",
            _("Options"),
            {
                "public-access": _("People Can Reach Me"),
                "public-links": _("Public Contacts"),
                "last-seen-public": _("Share Presence"),
                "address-expansion": _("Address Expansion"),
            },
        ),
    )

    _profile: model.Profile | None = None
    _broadcasts: bool = True
    _address: str | None = None
    _name: str | None = None
    _image: Gdk.Paintable | None = None

    _user: Self | None = None

    def set_from_profile(self, prof: model.Profile | None):
        """Set the properties of `self` from `profile`."""
        self._profile = prof

        if not prof:
            self.image = None
            return

        self.address = prof.address
        self.name = prof.name

    @Property(bool, default=True)
    def receive_broadcasts(self) -> bool:
        """Whether to receive broadcasts from the owner of the profile.

        See `Profile.set_receives_broadcasts()`.
        """
        return self._broadcasts

    @receive_broadcasts.setter
    def receive_broadcasts(self, receive_broadcasts: bool):
        from . import store

        if self._broadcasts == receive_broadcasts or (not self._profile):
            return

        self._broadcasts = receive_broadcasts

        tasks.create(store.broadcasts.update())
        tasks.create(
            contacts.new(
                self._profile.address,
                receive_broadcasts=receive_broadcasts,
            )
        )

    @Property(str)
    def address(self) -> str | None:
        """The profile owner's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str):
        self._address = address
        self.name = self.name or address

    @Property(str)
    def name(self) -> str | None:
        """The profile owner's name."""
        return self._name

    @name.setter
    def name(self, name: str):
        self._name = name
        self.has_name = name != self.address

    @Property(Gdk.Paintable)
    def image(self) -> Gdk.Paintable | None:
        """The profile owner's profile image."""
        return self._image

    @image.setter
    def image(self, image: Gdk.Paintable | None):
        self._image = image
        self.has_image = bool(image)

    @classmethod
    def of(cls, user: Address | User, /) -> "Profile":
        """Get the profile associated with `user`.

        If `user` is a User object instead of an Address,
        returns a `Profile` object that always represents the data of
        the currently logged in user, even after a relogin.
        """
        match user:
            case Address():
                from . import store

                (profile := store.profiles[user]).address = user
                return profile

            case User():
                if not cls._user:
                    cls._user = cls()

                return cls._user

    def value_of(self, ident: str) -> Any:  # noqa: ANN401
        """Get the value of the field identified by `ident` in `self`."""
        try:
            return getattr(self._profile, ident.replace("-", "_"))
        except AttributeError:
            return None

    def set_receives_broadcasts(self, value: bool):
        """Use this method to update the local state from remote data.

        Set `Profile.receive_broadcasts` to update the remote state as well.
        """
        if value == self._broadcasts:
            return

        self._broadcasts = value
        self.notify("receive-broadcasts")


# TODO: Maybe these could be methods of a subclass of Profile specific to the user
async def refresh():
    """Update the profile of the user by fetching new data remotely."""
    Profile.of(client.user).updating = True
    Profile.of(client.user).set_from_profile(
        prof := await profile.fetch(client.user.address)
    )

    if prof:
        client.user.signing_keys = KeyPair(
            client.user.signing_keys.private,
            prof.signing_key,
        )

        if prof.encryption_key:
            client.user.encryption_keys = KeyPair(
                client.user.encryption_keys.private,
                prof.encryption_key,
            )

    try:
        Profile.of(client.user).image = Gdk.Texture.new_from_bytes(
            GLib.Bytes.new(await profile.fetch_image(client.user.address))
        )
    except GLib.Error:
        Profile.of(client.user).image = None

    Profile.of(client.user.address).image = Profile.of(client.user).image
    Profile.of(client.user.address).set_from_profile(prof)
    Profile.of(client.user).updating = False


async def update(values: dict[str, str]):
    """Update the user's public profile with `values`."""
    try:
        await profile.update(values)
    except WriteError:
        Notifier.send(_("Failed to update profile"))
        raise

    await refresh()


async def update_image(pixbuf: GdkPixbuf.Pixbuf):
    """Upload `pixbuf` to be used as the user's profile image."""
    if (width := pixbuf.props.width) > (height := pixbuf.props.height):
        if width > MAX_IMAGE_DIMENSIONS:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=int(width * (MAX_IMAGE_DIMENSIONS / height)),
                    dest_height=MAX_IMAGE_DIMENSIONS,
                    interp_type=GdkPixbuf.InterpType.BILINEAR,
                )
                or pixbuf
            )

            width = pixbuf.props.width
            height = pixbuf.props.height

        pixbuf = pixbuf.new_subpixbuf(
            src_x=int((width - height) / 2),
            src_y=0,
            width=height,
            height=height,
        )
    else:
        if height > MAX_IMAGE_DIMENSIONS:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=MAX_IMAGE_DIMENSIONS,
                    dest_height=int(height * (MAX_IMAGE_DIMENSIONS / width)),
                    interp_type=GdkPixbuf.InterpType.BILINEAR,
                )
                or pixbuf
            )

            width = pixbuf.props.width
            height = pixbuf.props.height

        if height > width:
            pixbuf = pixbuf.new_subpixbuf(
                src_x=0,
                src_y=int((height - width) / 2),
                height=width,
                width=width,
            )

    try:
        success, data = pixbuf.save_to_bufferv(
            type="jpeg",
            option_keys=("quality",),
            option_values=("80",),
        )
    except GLib.Error as error:
        Notifier.send(_("Failed to update profile image"))
        raise WriteError from error

    if not success:
        Notifier.send(_("Failed to update profile image"))
        raise WriteError

    try:
        await profile.update_image(data)
    except WriteError:
        Notifier.send(_("Failed to update profile image"))
        raise

    await refresh()


async def delete_image():
    """Delete the user's profile image."""
    try:
        await profile.delete_image()
    except WriteError:
        Notifier.send(_("Failed to delete profile image"))
        raise

    await refresh()
