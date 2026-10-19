"""Riproduzione con libmpv: capitoli, velocità, posizione."""
from __future__ import annotations

import os
from pathlib import Path

import mpv


class Player:
    def __init__(self) -> None:
        self.mpv = mpv.MPV(video="no", audio_display="no", input_default_bindings=False,
                           input_vo_keyboard=False, osc=False, terminal=False,
                           keep_open="yes", force_window="no", ytdl=False,
                           **({"ao": os.environ["AUDIBLE_TUI_AO"]} if os.environ.get("AUDIBLE_TUI_AO") else {}))
        self.loaded = False

    def load(self, path: Path, start_s: float = 0.0) -> None:
        self.mpv.start = f"{max(start_s, 0):.3f}"
        self.mpv.play(str(path))
        self.mpv.pause = False
        self.loaded = True

    # --- stato ---
    @property
    def position(self) -> float:
        return float(self.mpv.time_pos or 0.0)

    @property
    def duration(self) -> float:
        return float(self.mpv.duration or 0.0)

    @property
    def paused(self) -> bool:
        return bool(self.mpv.pause)

    @property
    def ended(self) -> bool:
        return bool(self.mpv.eof_reached)

    @property
    def speed(self) -> float:
        return float(self.mpv.speed or 1.0)

    @property
    def chapters(self) -> list[tuple[float, str]]:
        return [(float(c["time"]), c.get("title") or f"Capitolo {i + 1}")
                for i, c in enumerate(self.mpv.chapter_list or [])]

    def chapter_index(self) -> int:
        pos, idx = self.position, 0
        for i, (t, _) in enumerate(self.chapters):
            if t <= pos + 0.05:
                idx = i
        return idx

    # --- comandi ---
    def toggle(self) -> None:
        self.mpv.pause = not self.mpv.pause

    def pause(self) -> None:
        self.mpv.pause = True

    def seek(self, delta: float) -> None:
        self.mpv.seek(delta, "relative")

    def seek_to(self, seconds: float) -> None:
        self.mpv.seek(max(seconds, 0), "absolute")

    def chapter(self, step: int) -> None:
        ch = self.chapters
        if not ch:
            return
        i = self.chapter_index()
        # "indietro" a metà capitolo riparte dall'inizio del capitolo
        if step < 0 and self.position - ch[i][0] > 3:
            target = i
        else:
            target = min(max(i + step, 0), len(ch) - 1)
        self.seek_to(ch[target][0])

    def set_speed(self, speed: float) -> None:
        self.mpv.speed = round(min(max(speed, 0.5), 3.0), 2)

    def volume(self, delta: int) -> None:
        self.mpv.volume = min(max((self.mpv.volume or 100) + delta, 0), 130)

    def close(self) -> None:
        try:
            self.mpv.terminate()
        except Exception:
            pass
