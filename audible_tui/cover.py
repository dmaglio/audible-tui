"""Copertina: scarica o estrae dal M4B e la disegna con mezzi blocchi colorati."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

import httpx
from PIL import Image
from rich.text import Text

from .api import Book
from .config import DATA_DIR

COVERS = DATA_DIR / "covers"


def get_cover(book: Book) -> Path | None:
    """Percorso della copertina in cache; la prende da Internet o dal M4B."""
    COVERS.mkdir(parents=True, exist_ok=True)
    dest = COVERS / f"{book.asin}.jpg"
    if dest.exists():
        return dest
    if book.cover_url:
        try:
            r = httpx.get(book.cover_url, timeout=20, follow_redirects=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest
        except httpx.HTTPError:
            pass
    src = book.path()
    if src:
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an",
                              "-frames:v", "1", str(dest)], capture_output=True)
        if res.returncode == 0 and dest.exists():
            return dest
    return None


@lru_cache(maxsize=16)
def render(path: str, cols: int) -> Text:
    """Quadrata, cols colonne per cols/2 righe: ogni cella è due pixel (▀)."""
    img = Image.open(path).convert("RGB").resize((cols, cols), Image.LANCZOS)
    px = img.load()
    out = Text(no_wrap=True, overflow="crop")
    for y in range(0, cols - 1, 2):
        for x in range(cols):
            top, bot = px[x, y], px[x, y + 1]
            out.append("▀", style=f"rgb({top[0]},{top[1]},{top[2]}) on rgb({bot[0]},{bot[1]},{bot[2]})")
        if y + 2 < cols - 1:
            out.append("\n")
    return out
