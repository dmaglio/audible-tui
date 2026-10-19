"""Accesso ad Audible: libreria, licenza di download, punto di ascolto."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import audible
import httpx
from audible.aescipher import decrypt_voucher_from_licenserequest

from .config import AUTH_FILE, BOOKS_DIR, DATA_DIR

UA = "Audible/671 CFNetwork/1240.0.4 Darwin/20.6.0"
GROUPS = "product_desc,product_attrs,contributors,series,media,is_finished,listening_status,percent_complete"
META_DIR = DATA_DIR / "meta"


@dataclass
class Book:
    asin: str
    title: str
    authors: str = ""
    narrators: str = ""
    series: str = ""
    seq: str = ""
    minutes: int = 0
    percent: float = 0.0
    finished: bool = False
    purchased: str = ""
    summary: str = ""
    cover_url: str = ""

    @property
    def sort_key(self) -> tuple:
        try:
            n = float(self.seq)
        except ValueError:
            n = 0.0
        return (self.series.lower() or "￿", n, self.title.lower())

    def path(self) -> Path | None:
        if not BOOKS_DIR.exists():
            return None
        for p in BOOKS_DIR.glob(f"*/*[[]{self.asin}[]].m4b"):
            return p
        return None


def _cover_url(images: dict) -> str:
    if not images:
        return ""
    return images[max(images, key=lambda k: int(k) if k.isdigit() else 0)]


def _book(i: dict) -> Book:
    ls = i.get("listening_status") or {}
    ser = (i.get("series") or [{}])[0]
    return Book(
        asin=i["asin"],
        title=i.get("title", "?"),
        authors=", ".join(a["name"] for a in i.get("authors", [])),
        narrators=", ".join(a["name"] for a in i.get("narrators", [])),
        series=ser.get("title", ""),
        seq=str(ser.get("sequence", "") or ""),
        minutes=int(i.get("runtime_length_min") or 0),
        percent=float(i.get("percent_complete") or ls.get("percent_complete") or 0),
        finished=bool(i.get("is_finished") or ls.get("is_finished")),
        purchased=(i.get("purchase_date") or "")[:10],
        summary=re.sub(r"<[^>]+>", "", i.get("merchandising_summary") or "").strip(),
        cover_url=_cover_url(i.get("product_images") or {}),
    )


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "?"


class Audible:
    def __init__(self) -> None:
        self.auth = audible.Authenticator.from_file(AUTH_FILE)
        if self.auth.access_token_expired:
            self.auth.refresh_access_token()
            self.auth.to_file(AUTH_FILE)
        self.client = audible.Client(self.auth)
        META_DIR.mkdir(parents=True, exist_ok=True)

    # --- libreria -------------------------------------------------------
    def cached_library(self) -> list[Book]:
        try:
            return [Book(**b) for b in json.loads((DATA_DIR / "library.json").read_text())]
        except (OSError, ValueError, TypeError):
            return []

    def library(self) -> list[Book]:
        items, page = [], 1
        while True:
            r = self.client.get("1.0/library", num_results=1000, page=page,
                                response_groups=GROUPS, sort_by="-PurchaseDate")
            got = r.get("items", [])
            items += got
            if len(got) < 1000:
                break
            page += 1
        books = [_book(i) for i in items]
        (DATA_DIR / "library.json").write_text(json.dumps([asdict(b) for b in books]))
        return books

    # --- punto di ascolto ------------------------------------------------
    def remote_positions(self, asins: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for k in range(0, len(asins), 25):
            r = self.client.get("1.0/annotations/lastpositions", asins=",".join(asins[k:k + 25]))
            for a in r.get("asin_last_position_heard_annots", []):
                lp = a.get("last_position_heard") or {}
                if lp.get("status") == "Exists":
                    out[a["asin"]] = int(lp["position_ms"])
        return out

    def set_position(self, asin: str, ms: int) -> None:
        meta = self.meta(asin)
        if not meta.get("acr"):
            meta = self.license(asin)[1]
        self.client.put(f"1.0/lastpositions/{asin}",
                        body={"acr": meta["acr"], "asin": asin, "position_ms": int(ms)})

    # --- metadati locali (acr, capitoli) ----------------------------------
    def meta(self, asin: str) -> dict:
        try:
            return json.loads((META_DIR / f"{asin}.json").read_text())
        except (OSError, ValueError):
            return {}

    def send_stats(self, events: list[dict]) -> None:
        if events:
            self.client.put("1.0/stats/events", body={
                "stats": events,
                "device_type_id": self.auth.device_info.get("device_type", "")})

    # --- download --------------------------------------------------------
    def license(self, asin: str):
        body = {"supported_drm_types": ["Mpeg", "Adrm"], "quality": "High",
                "consumption_type": "Download",
                "response_groups": "last_position_heard,content_reference,chapter_info"}
        r = self.client.post(f"1.0/content/{asin}/licenserequest", body=body)
        cl = r["content_license"]
        md = cl["content_metadata"]
        info = md.get("chapter_info", {})
        meta = {"acr": md["content_reference"]["acr"],
                "license_id": cl.get("license_id", ""),
                "length_ms": info.get("runtime_length_ms", 0),
                "chapters": info.get("chapters", [])}
        (META_DIR / f"{asin}.json").write_text(json.dumps(meta))
        return r, meta

    def download(self, book: Book, progress: Callable[[str, float], None]) -> Path:
        """Scarica e decifra in M4B (capitoli e copertina compresi)."""
        r, _ = self.license(book.asin)
        voucher = decrypt_voucher_from_licenserequest(self.auth, r)
        url = r["content_license"]["content_metadata"]["content_url"]["offline_url"]
        dest_dir = BOOKS_DIR / safe(book.authors.split(",")[0] or "Sconosciuto")
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest_dir / f".{book.asin}.aax"
        final = dest_dir / f"{safe(book.title)} [{book.asin}].m4b"
        try:
            with httpx.stream("GET", url, headers={"User-Agent": UA},
                              follow_redirects=True, timeout=60) as s, open(tmp, "wb") as f:
                s.raise_for_status()
                total = int(s.headers.get("content-length") or 0)
                done = 0
                for chunk in s.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        progress("download", done / total)
            progress("decifro", 1.0)
            part = final.with_suffix(".part.m4b")
            cmd = ["ffmpeg", "-v", "error", "-y"]
            if "key" in voucher:
                cmd += ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]
            subprocess.run(cmd + ["-i", str(tmp), "-c", "copy", str(part)], check=True)
            shutil.move(part, final)
        finally:
            tmp.unlink(missing_ok=True)
        return final
