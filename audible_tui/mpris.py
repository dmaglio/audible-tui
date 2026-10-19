"""Server MPRIS: i tasti multimediali (playerctl) comandano il player.

Avanti e indietro saltano di SKIP secondi invece che di capitolo, come si usa
per gli audiolibri.
"""
from typing import Callable

from dbus_fast import PropertyAccess, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, dbus_property, method

NAME = "org.mpris.MediaPlayer2.audible_tui"
PATH = "/org/mpris/MediaPlayer2"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"


class Root(ServiceInterface):
    def __init__(self, quit_cb: Callable[[], None]) -> None:
        super().__init__("org.mpris.MediaPlayer2")
        self._quit = quit_cb

    @method()
    def Raise(self):
        pass

    @method()
    def Quit(self):
        self._quit()

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "Audible TUI"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class PlayerIface(ServiceInterface):
    def __init__(self, ctl) -> None:
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.ctl = ctl

    # --- comandi ---
    @method()
    def Next(self):
        self.ctl.skip(+self.ctl.SKIP)

    @method()
    def Previous(self):
        self.ctl.skip(-self.ctl.SKIP)

    @method()
    def Pause(self):
        self.ctl.set_paused(True)

    @method()
    def PlayPause(self):
        self.ctl.toggle()

    @method()
    def Stop(self):
        self.ctl.set_paused(True)

    @method()
    def Play(self):
        self.ctl.set_paused(False)

    @method()
    def Seek(self, offset: "x"):
        self.ctl.skip(offset / 1_000_000)

    @method()
    def SetPosition(self, track_id: "o", position: "x"):
        self.ctl.seek_to(position / 1_000_000)

    @method()
    def OpenUri(self, uri: "s"):
        pass

    # --- proprietà ---
    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self.ctl.status()

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return self.ctl.rate()

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return 0.5

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return 3.0

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return self.ctl.metadata()

    @dbus_property(access=PropertyAccess.READ)
    def Volume(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return int(self.ctl.position() * 1_000_000)

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return self.ctl.active()

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return self.ctl.active()

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return self.ctl.active()

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return self.ctl.active()

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return self.ctl.active()

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return True


class Mpris:
    """Collega l'app a D-Bus. `ctl` espone stato e comandi (vedi app.py)."""

    def __init__(self, ctl, quit_cb: Callable[[], None]) -> None:
        self.ctl = ctl
        self.root = Root(quit_cb)
        self.player = PlayerIface(ctl)
        self.bus: MessageBus | None = None
        self._last: tuple | None = None

    async def start(self) -> None:
        self.bus = await MessageBus().connect()
        self.bus.export(PATH, self.root)
        self.bus.export(PATH, self.player)
        await self.bus.request_name(NAME)

    def update(self) -> None:
        """Annuncia i cambi di stato (play/pausa, libro, velocità)."""
        state = (self.ctl.status(), self.ctl.rate(), self.ctl.track_id())
        if state == self._last:
            return
        self._last = state
        self.player.emit_properties_changed(
            {"PlaybackStatus": self.ctl.status(), "Rate": self.ctl.rate(),
             "Metadata": self.ctl.metadata(), "CanGoNext": self.ctl.active(),
             "CanGoPrevious": self.ctl.active(), "CanPlay": self.ctl.active(),
             "CanPause": self.ctl.active(), "CanSeek": self.ctl.active()})

    async def stop(self) -> None:
        if self.bus:
            self.bus.disconnect()


def metadata(asin: str, title: str, artist: str, album: str, length_s: float) -> dict:
    return {
        "mpris:trackid": Variant("o", f"/org/audible_tui/{asin}"),
        "mpris:length": Variant("x", int(length_s * 1_000_000)),
        "xesam:title": Variant("s", title),
        "xesam:artist": Variant("as", [artist]),
        "xesam:album": Variant("s", album),
    }
