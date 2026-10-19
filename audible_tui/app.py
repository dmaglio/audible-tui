"""Interfaccia a terminale per gli audiolibri di Audible Italia."""
from __future__ import annotations

import json
import os
import time

from rich.console import Group
from rich.text import Text

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets.data_table import ColumnKey
from textual.widgets._footer import FooterKey
from textual.widgets import DataTable, Footer, Header, Input, ProgressBar, Static

from .api import Audible, Book
from .mpris import Mpris, metadata as mpris_metadata
from .config import DATA_DIR
from .cover import get_cover, render
from .player import Player
from .stats import ListeningSession
from .themes import PALETTES, all_themes

SYNC_EVERY = 30  # secondi tra due scritture del punto di ascolto
SKIP = 15  # secondi di salto, per le frecce e per i tasti multimediali


def hms(s: float) -> str:
    s = int(max(s, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


class MprisControl:
    """Stato e comandi che il server MPRIS chiede all'app."""

    SKIP = SKIP

    def __init__(self, app: "AudibleApp") -> None:
        self.app = app

    def active(self) -> bool:
        return bool(self.app.player and self.app.current and self.app.player.loaded)

    def status(self) -> str:
        if not self.active():
            return "Stopped"
        return "Paused" if self.app.player.paused else "Playing"

    def rate(self) -> float:
        return self.app.player.speed if self.active() else 1.0

    def position(self) -> float:
        return self.app.player.position if self.active() else 0.0

    def track_id(self) -> str:
        return self.app.current.asin if self.active() else ""

    def metadata(self) -> dict:
        if not self.active():
            return {}
        b = self.app.current
        return mpris_metadata(b.asin, b.title, b.authors, b.series or b.title,
                              self.app.player.duration)

    def skip(self, seconds: float) -> None:
        if self.active():
            self.app.player.seek(seconds)

    def seek_to(self, seconds: float) -> None:
        if self.active():
            self.app.player.seek_to(seconds)

    def set_paused(self, paused: bool) -> None:
        if self.active() and self.app.player.paused != paused:
            self.app.action_toggle()

    def toggle(self) -> None:
        if self.active():
            self.app.action_toggle()


class QuietFooter(Footer):
    """Footer solo informativo: i click del mouse non premono tasti.

    Ridimensionando la finestra (SUPER + tasto destro) il mouse passava sul footer
    e il mouse-down su "Vel +" o "Tema" simulava il tasto."""

    def on_mount(self) -> None:
        FooterKey.on_mouse_down = lambda self: None


class AudibleApp(App):
    TITLE = "Audible Italia"
    CSS = """
    #main { height: 1fr; }
    #lib { width: 1fr; height: 1fr; }
    #side { width: 44; height: 1fr; border-left: solid $primary; padding: 0 1; }
    #search { display: none; }
    #search.on { display: block; }
    #now { height: 5; border-top: solid $primary; padding: 0 1; }
    #bar { width: 1fr; }
    """
    BINDINGS = [
        Binding("enter", "play", "Ascolta", show=True),
        Binding("space", "toggle", "Pausa", key_display="Spazio"),
        Binding("left,h", "seek(-15)", "-15s", key_display="←"),
        Binding("right,l", "seek(15)", "+15s", key_display="→"),
        Binding("shift+left,H", "seek(-300)", "-5m", show=False),
        Binding("shift+right,L", "seek(300)", "+5m", show=False),
        Binding("comma", "chapter(-1)", "Cap. prec.", key_display=","),
        Binding("full_stop", "chapter(1)", "Cap. succ.", key_display="."),
        Binding("plus", "speed(0.1)", "Vel +", key_display="+"),
        Binding("equals_sign", "speed(0.1)", show=False),
        Binding("minus", "speed(-0.1)", "Vel -", key_display="-"),
        Binding("t", "theme", "Tema"),
        Binding("z", "sleep", "Sleep"),
        Binding("d", "download", "Scarica"),
        Binding("r", "refresh", "Aggiorna"),
        Binding("slash", "search", "Cerca", key_display="/"),
        Binding("escape", "clear_search", show=False),
        Binding("q", "quit", "Esci"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.api = Audible()
        self.player: Player | None = None
        self.books: list[Book] = []
        self.remote: dict[str, int] = {}
        self.current: Book | None = None
        self.last_sync = 0.0
        self.last_synced_pos = -1.0
        self.sleep_at: float | None = None
        self.busy: set[str] = set()
        self._side_key: tuple | None = None
        self.session: ListeningSession | None = None
        self.mpris = Mpris(MprisControl(self), lambda: self.call_later(self.action_quit))
        self.filter = ""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Cerca titolo, autore, serie…", id="search")
        with Horizontal(id="main"):
            yield DataTable(id="lib", cursor_type="row", zebra_stripes=True)
            yield Static("", id="side")
        with Vertical(id="now"):
            yield Static("Niente in riproduzione", id="info")
            yield ProgressBar(total=1, show_eta=False, show_percentage=False, id="bar")
            yield Static("", id="status")
        yield QuietFooter()

    async def on_event(self, event: events.Event) -> None:
        # diagnostica: AUDIBLE_TUI_DEBUG=1 scrive tasti, mouse e azioni in debug.log
        if os.environ.get("AUDIBLE_TUI_DEBUG") and isinstance(
                event, (events.Key, events.MouseDown, events.MouseUp, events.Resize, events.Paste)):
            with open(DATA_DIR / "debug.log", "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {event!r}\n")
        if isinstance(event, events.Key) and self.swallow_osc(event):
            return
        await super().on_event(event)

    _osc_since = 0.0   # inizio di una sequenza OSC non riconosciuta (0 = nessuna)
    _osc_prev = ""

    def swallow_osc(self, ev: events.Key) -> bool:
        """Scarta le sequenze OSC che kitty manda sul mouse (ESC ] 72 ; t=o:x=..: ... ESC \\).

        Textual non le riconosce e le consegna come tasti: i caratteri "t" e "="
        cambiavano tema e velocità."""
        ch, now = ev.character or "", time.monotonic()
        if self._osc_since and now - self._osc_since > 0.5:
            self._osc_since = 0.0
        if not self._osc_since and self._osc_prev == "^" and ch == "]":
            self._osc_since = now
        self._osc_prev = ch
        if self._osc_since:
            if ch == "\\":
                self._osc_since = 0.0
            return True
        return False

    async def run_action(self, action, *args, **kwargs):
        if os.environ.get("AUDIBLE_TUI_DEBUG"):
            with open(DATA_DIR / "debug.log", "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} ACTION {action}\n")
        return await super().run_action(action, *args, **kwargs)

    def on_mount(self) -> None:
        for th in all_themes():
            self.register_theme(th)
        self.theme = f"catppuccin-{self.saved_theme()}"
        t = self.query_one("#lib", DataTable)
        t.add_column("", key="dl", width=2)
        t.add_column("Titolo", key="title", width=30)
        t.add_column("Autore", key="author", width=18)
        t.add_column("Serie", key="series", width=20)
        t.add_column("Durata", key="dur", width=7)
        t.add_column("Ascolto", key="pct", width=8)
        self.books = sorted(self.api.cached_library(), key=lambda b: b.sort_key)
        self.fill()
        self.set_interval(1.0, self.tick)
        self.fetch_library()
        self.start_mpris()
        t.focus()

    @work(exclusive=True, group="mpris")
    async def start_mpris(self) -> None:
        try:
            await self.mpris.start()
        except Exception as e:  # niente bus di sessione: si va avanti senza tasti multimediali
            self.status(f"MPRIS non attivo: {e}")

    # --- pannello laterale ----------------------------------------------
    def on_resize(self, ev: events.Resize) -> None:
        t = self.query_one("#lib", DataTable)
        if not t.columns:
            return
        # larghezza della tabella = schermo - pannello (44); tolgo colonne fisse e spaziatura
        free = max(ev.size.width - 44 - 2 - 7 - 8 - 6 * 2 - 2, 30)  # colonne fisse e spaziatura
        for key, share in (("title", 0.42), ("author", 0.26), ("series", 0.32)):
            t.columns[ColumnKey(key)].width = max(int(free * share), 8)
        t.refresh(layout=True)
        self.call_after_refresh(self.update_side, True)

    @on(DataTable.RowHighlighted)
    def _highlighted(self) -> None:
        self.update_side()

    def side_target(self) -> Book | None:
        return self.current or self.selected()

    def update_side(self, force: bool = False) -> None:
        b = self.side_target()
        side = self.query_one("#side", Static)
        if not b:
            side.update("")
            return
        key = (b.asin, side.size.width, side.size.height)
        if key == self._side_key and not force:
            return
        self._side_key = key
        self.load_side(b, side.size.width - 3, side.size.height)

    @work(thread=True, exclusive=True, group="side")
    def load_side(self, b: Book, width: int, height: int) -> None:
        path = get_cover(b)
        self.call_from_thread(self.show_side, b, path, width, height)

    def show_side(self, b: Book, path, width: int, height: int) -> None:
        width = max(width, 10)
        cols = max(min(width, 2 * (height - 12)) // 2 * 2, 8)
        parts: list = []
        used = 0
        if path:
            cover = render(str(path), cols)
            cover.justify = "center"
            parts.append(cover)
            used = cols // 2
        parts.append(Text(""))
        parts.append(Text(b.title, style="bold"))
        parts.append(Text(b.authors, style="italic"))
        if b.narrators:
            parts.append(Text.assemble(("Letto da ", "dim"), b.narrators))
        if b.series:
            parts.append(Text.assemble(("Serie ", "dim"), b.series + (f" #{b.seq}" if b.seq else "")))
        parts.append(Text.assemble(("Durata ", "dim"), hm(b.minutes)))
        room = height - used - 9 - len(b.title) // max(width, 1)
        if b.summary and room > 1:
            parts.append(Text(""))
            parts.append(Text(b.summary[: room * width].rsplit(" ", 1)[0] + "…"
                              if len(b.summary) > room * width else b.summary, style="dim"))
        self.query_one("#side", Static).update(Group(*parts))

    # --- libreria -----------------------------------------------------
    @work(thread=True, exclusive=True, group="lib")
    def fetch_library(self) -> None:
        self.status("Aggiorno la libreria…")
        try:
            books = sorted(self.api.library(), key=lambda b: b.sort_key)
        except Exception as e:  # rete assente: resta la cache
            self.status(f"Libreria non aggiornata: {e}")
            return
        try:
            remote = self.api.remote_positions([b.asin for b in books])
        except Exception as e:
            self.status(f"Punti di ascolto non letti: {e}")
            remote = self.remote
        self.call_from_thread(self.set_library, books, remote)

    def set_library(self, books: list[Book], remote: dict[str, int]) -> None:
        self.books, self.remote = books, remote
        self.fill()
        self.update_side(force=True)
        self.status(f"{len(books)} audiolibri")

    def shown(self) -> list[Book]:
        f = self.filter.lower()
        return [b for b in self.books
                if not f or f in f"{b.title} {b.authors} {b.series}".lower()]

    def row(self, b: Book) -> tuple:
        pct = "finito" if b.finished else (f"{b.percent:.0f}%" if b.percent else "")
        mark = "⏬" if b.asin in self.busy else ("●" if b.path() else "")
        series = f"{b.series} #{b.seq}" if b.series and b.seq else b.series
        return (mark, b.title, b.authors, series, hm(b.minutes), pct)

    def fill(self) -> None:
        t = self.query_one("#lib", DataTable)
        keep = self.selected().asin if self.selected() else None
        t.clear()
        for b in self.shown():
            t.add_row(*self.row(b), key=b.asin)
        if keep:
            try:
                t.move_cursor(row=t.get_row_index(keep))
            except Exception:
                pass

    def selected(self) -> Book | None:
        t = self.query_one("#lib", DataTable)
        if not t.row_count:
            return None
        key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        return next((b for b in self.books if b.asin == key), None)

    def refresh_row(self, b: Book) -> None:
        t = self.query_one("#lib", DataTable)
        try:
            for col, val in zip(("dl", "title", "author", "series", "dur", "pct"), self.row(b)):
                t.update_cell(b.asin, col, val)
        except Exception:
            pass

    # --- ricerca ------------------------------------------------------
    def action_search(self) -> None:
        s = self.query_one("#search", Input)
        s.add_class("on")
        s.focus()

    @on(Input.Changed, "#search")
    def _filter(self, ev: Input.Changed) -> None:
        self.filter = ev.value
        self.fill()

    @on(Input.Submitted, "#search")
    def _done(self) -> None:
        self.query_one("#lib").focus()

    def action_clear_search(self) -> None:
        s = self.query_one("#search", Input)
        s.value = ""
        s.remove_class("on")
        self.query_one("#lib").focus()

    # --- download -----------------------------------------------------
    def action_download(self) -> None:
        b = self.selected()
        if b and not b.path():
            self.download(b, play=False)

    @work(thread=True, group="dl")
    def download(self, b: Book, play: bool) -> None:
        if b.asin in self.busy:
            return
        self.busy.add(b.asin)
        self.call_from_thread(self.refresh_row, b)
        last = [0.0]

        def progress(stage: str, frac: float) -> None:
            if time.monotonic() - last[0] > 0.5 or frac >= 1:
                last[0] = time.monotonic()
                msg = "Decifro…" if stage == "decifro" else f"Scarico «{b.title}» {frac:4.0%}"
                self.status(msg)

        try:
            self.api.download(b, progress)
        except Exception as e:
            self.status(f"Download fallito: {e}")
        else:
            self.status(f"Scaricato «{b.title}»")
        finally:
            self.busy.discard(b.asin)
            self.call_from_thread(self.refresh_row, b)
        if play and b.path():
            self.call_from_thread(self.start, b)

    @on(DataTable.RowSelected)
    def _selected(self) -> None:
        self.action_play()

    # --- riproduzione -------------------------------------------------
    def action_play(self) -> None:
        b = self.selected()
        if not b:
            return
        if b.asin in self.busy:
            return
        if self.current and self.current.asin == b.asin and self.player:
            return self.action_toggle()
        if b.path():
            self.start(b)
        else:
            self.download(b, play=True)

    def start(self, b: Book) -> None:
        self.flush_position()
        self.stats_close()
        if self.player is None:
            self.player = Player()
        self.current = b
        ms = self.remote.get(b.asin, 0)
        if b.finished and not ms:
            ms = 0
        self.player.load(b.path(), ms / 1000)
        self.last_sync = time.monotonic()
        self.last_synced_pos = -1
        self.update_side()
        self.begin_session(b)
        self.status(f"Riprendo da {hms(ms / 1000)}" if ms else "Parto dall'inizio")

    def action_toggle(self) -> None:
        if self.player and self.current:
            self.player.toggle()
            if self.player.paused:
                self.flush_position()

    def action_seek(self, delta: float) -> None:
        if self.player and self.current:
            self.player.seek(delta)

    def action_chapter(self, step: int) -> None:
        if self.player and self.current:
            self.player.chapter(step)

    def action_speed(self, delta: float) -> None:
        if self.player and self.current:
            self.player.set_speed(self.player.speed + delta)

    def action_sleep(self) -> None:
        steps = [None, 15, 30, 45, 60]
        cur = getattr(self, "_sleep_min", None)
        nxt = steps[(steps.index(cur) + 1) % len(steps)]
        self._sleep_min = nxt
        self.sleep_at = time.monotonic() + nxt * 60 if nxt else None
        self.status(f"Sleep timer: {nxt} minuti" if nxt else "Sleep timer spento")

    # --- tick, sincronizzazione ----------------------------------------
    def tick(self) -> None:
        info, bar = self.query_one("#info", Static), self.query_one("#bar", ProgressBar)
        self.mpris.update()
        p, b = self.player, self.current
        if not (p and b and p.loaded):
            return
        pos, dur = p.position, p.duration
        ch = p.chapters
        ci = p.chapter_index()
        chname = ch[ci][1] if ch else ""
        state = "⏸" if p.paused else "▶"
        sleep = ""
        if self.sleep_at:
            left = self.sleep_at - time.monotonic()
            if left <= 0:
                p.pause()
                self.sleep_at = None
                self._sleep_min = None
                self.flush_position()
            else:
                sleep = f"  ☾ {int(left // 60) + 1}m"
        info.update(f"{state} [b]{b.title}[/b] — {b.authors}\n"
                    f"{chname}  ({ci + 1}/{len(ch)})" if ch else f"{state} {b.title}")
        bar.update(total=max(dur, 1), progress=pos)
        self.query_one("#status", Static).update(
            f"{hms(pos)} / {hms(dur)}   {p.speed:g}x{sleep}")
        if time.monotonic() - self.last_sync >= SYNC_EVERY and not p.paused:
            self.flush_position()
        self.stats_tick()
        if p.ended and not b.finished:
            b.finished = True
            self.flush_position(final=True)
            self.stats_close(finished=True)

    def flush_position(self, final: bool = False) -> None:
        p, b = self.player, self.current
        if not (p and b and p.loaded):
            return
        pos = p.position
        self.last_sync = time.monotonic()
        if abs(pos - self.last_synced_pos) < 1:
            return
        self.last_synced_pos = pos
        self.remote[b.asin] = int(pos * 1000)
        if p.duration:
            b.percent = pos / p.duration * 100
            self.refresh_row(b)
        self.push(b.asin, int(pos * 1000))

    # --- eventi di ascolto (barra di avanzamento di Audible) --------------
    @work(thread=True, group="session")
    def begin_session(self, b: Book) -> None:
        try:
            meta = self.api.meta(b.asin)
            if not meta.get("license_id"):
                _, meta = self.api.license(b.asin)
            length = meta.get("length_ms") or int((self.player.duration if self.player else 0) * 1000)
            session = ListeningSession(b.asin, meta.get("license_id", ""), length)
        except Exception as e:
            self.status(f"Eventi di ascolto non attivi: {e}")
            return
        if self.current and self.current.asin == b.asin:
            self.session = session

    @work(thread=True, group="stats")
    def send_stats(self, events: list[dict]) -> None:
        try:
            self.api.send_stats(events)
        except Exception as e:
            self.status(f"Eventi di ascolto non inviati: {e}")

    def stats_tick(self) -> None:
        p, ss = self.player, self.session
        if not (p and ss and self.current and ss.asin == self.current.asin and p.loaded):
            return
        evs = ss.tick(p.position * 1000, not p.paused and not p.ended, p.speed)
        if evs:
            self.send_stats(evs)

    def stats_close(self, finished: bool = False) -> None:
        p, ss = self.player, self.session
        if not (p and ss and p.loaded):
            return
        evs = ss.end(p.position * 1000, p.speed)
        if finished:
            evs += ss.finished(p.speed)
        if evs:
            self.send_stats(evs)

    @work(thread=True, group="sync")
    def push(self, asin: str, ms: int) -> None:
        try:
            self.api.set_position(asin, ms)
        except Exception as e:
            self.status(f"Sincronizzazione fallita: {e}")

    def status(self, msg: str) -> None:
        def show() -> None:
            self.sub_title = msg
        try:
            self.call_from_thread(show)
        except RuntimeError:
            show()

    # --- tema -----------------------------------------------------------
    def saved_theme(self) -> str:
        try:
            name = (DATA_DIR / "theme").read_text().strip()
        except OSError:
            name = ""
        return name if name in PALETTES else self.dark_name()

    def dark_name(self) -> str:
        return "macchiato"

    def action_theme(self) -> None:
        """Alterna tra Latte (chiaro) e Macchiato (scuro)."""
        name = self.dark_name() if self.theme == "catppuccin-latte" else "latte"
        self.theme = f"catppuccin-{name}"
        try:
            (DATA_DIR / "theme").write_text(name)
        except OSError:
            pass
        self.status(f"Tema: Catppuccin {name.capitalize()}")

    def action_refresh(self) -> None:
        self.fetch_library()

    # --- uscita -------------------------------------------------------
    async def action_quit(self) -> None:
        self.flush_position()
        self.stats_close()
        # il thread di push è daemon-ish: aspetto che finisca prima di uscire
        await self.workers.wait_for_complete()
        await self.mpris.stop()
        if self.player:
            self.player.close()
        self.exit()


def main() -> None:
    AudibleApp().run()


if __name__ == "__main__":
    main()
