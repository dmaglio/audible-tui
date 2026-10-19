# audible-tui

A terminal audiobook player for [Audible](https://www.audible.com), written for
Audible Italia (marketplace `it`) but usable with any marketplace the
[`audible`](https://github.com/mkb79/Audible) library supports.

- browse your library (title, author, series, length, progress, downloaded)
- download a book once, decrypt it locally to M4B (chapters and cover kept)
- listen with mpv: chapters, speed, ±30 s / ±5 min, sleep timer
- **listening position synced with Audible**: it resumes from where the web
  player or the phone app left you, and writes it back every 30 seconds, on
  pause and on exit

*Italiano:* player da terminale per gli audiolibri di Audible. Mostra la
libreria, scarica e decifra i libri in M4B, li ascolta con mpv e sincronizza il
punto di ascolto con Audible (sito e app ufficiale). L'interfaccia è in italiano.

## Requirements

Python ≥ 3.11, `ffmpeg`, and `libmpv` (Fedora: `mpv-libs`, Debian/Ubuntu:
`libmpv2`, Arch: `mpv`).

## Install

```sh
git clone https://github.com/dmaglio/audible-tui
cd audible-tui
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/audible-tui-login     # once: open the URL, sign in, paste the final address
.venv/bin/audible-tui
```

Login uses your browser (so 2FA/captcha work). What is stored is a device
registration token, not your password, in `~/.config/audible-tui/auth.json`
(mode 600). Treat that file like a password.

## Keys

| key | action |
|---|---|
| Enter | play (downloads first if needed) |
| Space | pause |
| ← / → (h / l) | −30 s / +30 s |
| Shift+← / → | −5 min / +5 min |
| `,` / `.` | previous / next chapter |
| `+` / `-` | speed |
| `z` | sleep timer: 15 / 30 / 45 / 60 min / off |
| `d` | download only |
| `/` | search (Esc clears) |
| `r` | refresh library |
| `q` | quit (writes the position first) |

## Settings (environment variables)

| variable | default |
|---|---|
| `AUDIBLE_TUI_LOCALE` | `it` (also `de`, `fr`, `uk`, `us`, …) |
| `AUDIBLE_TUI_BOOKS` | `~/Audiolibri` |

Books are saved as `<books dir>/<author>/<title> [ASIN].m4b`.

## Notes

- This tool is for listening to audiobooks **you have bought**, on your own
  devices. Downloaded files are decrypted with the key Audible itself hands to
  your registered device; don't share them.
- It uses unofficial, undocumented Audible endpoints through the `audible`
  library; they can change without notice.
- Not affiliated with Audible or Amazon.

## License

AGPL-3.0-or-later, the same as the `audible` library it builds on.
