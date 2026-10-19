"""Interfaccia a terminale per gli audiolibri di Audible Italia."""
from __future__ import annotations

import json
import time

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, ProgressBar, Static

from .api import Audible, Book
from .config import DATA_DIR
from .player import Player

SYNC_EVERY = 30  # secondi tra due scritture del punto di ascolto
SKIP = 30


def hms(s: float) -> str:
    s = int(max(s, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


class AudibleApp(App):
    TITLE = "Audible Italia"
    CSS = """
    #lib { height: 1fr; }
    #search { display: none; }
    #search.on { display: block; }
    #now { height: 5; border-top: solid $primary; padding: 0 1; }
    #bar { width: 1fr; }
    """
    BINDINGS = [
        Binding("enter", "play", "Ascolta", show=True),
        Binding("space", "toggle", "Pausa"),
        Binding("left,h", "seek(-30)", "-30s", show=False),
        Binding("right,l", "seek(30)", "+30s", show=False),
        Binding("shift+left,H", "seek(-300)", "-5m", show=False),
        Binding("shift+right,L", "seek(300)", "+5m", show=False),
        Binding("comma", "chapter(-1)", "Cap. prec.", show=False),
        Binding("full_stop", "chapter(1)", "Cap. succ.", show=False),
        Binding("plus,equals_sign", "speed(0.1)", "Velocità +", show=False),
        Binding("minus", "speed(-0.1)", "Velocità -", show=False),
        Binding("z", "sleep", "Sleep"),
        Binding("d", "download", "Scarica"),
        Binding("r", "refresh", "Aggiorna"),
        Binding("slash", "search", "Cerca"),
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
        self.filter = ""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Cerca titolo, autore, serie…", id="search")
        yield DataTable(id="lib", cursor_type="row", zebra_stripes=True)
        with Vertical(id="now"):
            yield Static("Niente in riproduzione", id="info")
            yield ProgressBar(total=1, show_eta=False, show_percentage=False, id="bar")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#lib", DataTable)
        t.add_column("", key="dl", width=2)
        t.add_column("Titolo", key="title", width=44)
        t.add_column("Autore", key="author", width=24)
        t.add_column("Serie", key="series", width=26)
        t.add_column("Durata", key="dur", width=7)
        t.add_column("Ascolto", key="pct", width=8)
        self.books = sorted(self.api.cached_library(), key=lambda b: b.sort_key)
        self.fill()
        self.set_interval(1.0, self.tick)
        self.fetch_library()
        t.focus()

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
        if self.player is None:
            self.player = Player()
        self.current = b
        ms = self.remote.get(b.asin, 0)
        if b.finished and not ms:
            ms = 0
        self.player.load(b.path(), ms / 1000)
        self.last_sync = time.monotonic()
        self.last_synced_pos = -1
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
        if p.ended and not b.finished:
            b.finished = True
            self.flush_position(final=True)

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

    def action_refresh(self) -> None:
        self.fetch_library()

    # --- uscita -------------------------------------------------------
    async def action_quit(self) -> None:
        self.flush_position()
        # il thread di push è daemon-ish: aspetto che finisca prima di uscire
        await self.workers.wait_for_complete()
        if self.player:
            self.player.close()
        self.exit()


def main() -> None:
    AudibleApp().run()


if __name__ == "__main__":
    main()
