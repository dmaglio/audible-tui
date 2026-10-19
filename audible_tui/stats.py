"""Eventi di ascolto per Audible (`PUT 1.0/stats/events`).

La posizione (`lastpositions`) basta per riprendere da dove si era, ma la barra
di avanzamento e la percentuale della libreria le aggiornano solo questi eventi,
come fa l'app ufficiale: StartListening quando parte l'ascolto, Listening con
inizio e fine di ogni tratto ascoltato (alla pausa, ogni minuto, dopo un salto).
Le posizioni sono in millisecondi.
"""
from __future__ import annotations

import datetime
import random
import string
import time

ROLL_EVERY = 60.0   # secondi: chiude e riapre il tratto d'ascolto
JUMP_MS = 3000      # scarto oltre il quale si considera un salto
MIN_MS = 1000       # tratti più corti non si inviano


def iso(t: datetime.datetime | None = None) -> str:
    t = t or datetime.datetime.now(datetime.UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class ListeningSession:
    def __init__(self, asin: str, license_id: str, length_ms: int, offline: bool = True) -> None:
        self.asin = asin
        self.license_id = license_id
        self.length_ms = int(length_ms)
        self.offline = offline
        self.session_id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        self._start: tuple[float, datetime.datetime, float] | None = None  # pos, quando, monotonic
        self._last: tuple[float, float] | None = None  # pos, monotonic

    # --- eventi ---------------------------------------------------------
    def _base(self, event_type: str, ts: datetime.datetime, speed: float) -> dict:
        return {
            "asin": self.asin, "event_type": event_type, "event_timestamp": iso(ts),
            "local_timezone": "Europe/Rome", "length_of_book": self.length_ms,
            "license_id": self.license_id, "audio_type": "FullTitle",
            "delivery_type": "Download" if self.offline else "Streaming",
            "listening_mode": "Offline" if self.offline else "Online",
            "store": "Audible", "narration_speed": speed, "version_of_app": "1",
            "session_id": self.session_id, "asin_owned": True,
        }

    def begin(self, pos: float, speed: float, announce: bool = True) -> list[dict]:
        now = datetime.datetime.now(datetime.UTC)
        self._start = (pos, now, time.monotonic())
        self._last = (pos, time.monotonic())
        if not announce:
            return []
        start = self._base("StartListening", now, speed)
        start["event_start_position"] = pos
        return [start, self._base("MarkAsUnfinished", now, speed)]

    def end(self, pos: float, speed: float) -> list[dict]:
        """Chiude il tratto in corso (se c'è e non è trascurabile)."""
        st, self._start, self._last = self._start, None, None
        if not st or pos - st[0] < MIN_MS:
            return []
        ev = self._base("Listening", st[1], speed)
        ev.update(event_start_position=st[0], event_end_position=pos,
                  event_end_timestamp=iso())
        return [ev]

    def finished(self, speed: float) -> list[dict]:
        return [self._base("MarkAsFinished", datetime.datetime.now(datetime.UTC), speed)]

    def tick(self, pos: float, playing: bool, speed: float) -> list[dict]:
        """Chiamata ogni secondo con la posizione (ms); restituisce gli eventi da inviare."""
        now = time.monotonic()
        if not playing:
            return self.end(pos, speed) if self._start else []
        if not self._start:
            return self.begin(pos, speed)
        last_pos, last_t = self._last
        expected = last_pos + (now - last_t) * 1000 * speed
        if abs(pos - expected) > JUMP_MS:  # salto: il tratto finisce dov'ero, ne comincia un altro
            return self.end(last_pos, speed) + self.begin(pos, speed, announce=False)
        self._last = (pos, now)
        if now - self._start[2] >= ROLL_EVERY:
            return self.end(pos, speed) + self.begin(pos, speed, announce=False)
        return []
