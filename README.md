# audible-tui

A terminal audiobook player for [Audible](https://www.audible.com), written for
Audible Italia (marketplace `it`) but usable with any marketplace the
[`audible`](https://github.com/mkb79/Audible) library supports.

- browse your library (title, author, series, length, progress, downloaded)
- download a book once, decrypt it locally to M4B (chapters and cover kept)
- side panel with the cover (drawn in the terminal with half-block characters), title, author, narrator, series and blurb of what is playing (or of the selected book)
- listen with mpv: chapters, speed, ±15 s / ±5 min, sleep timer
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
| ← / → (h / l) | −15 s / +15 s |
| Shift+← / → | −5 min / +5 min |
| `,` / `.` | previous / next chapter |
| `+` / `-` | speed |
| `t` | theme: Catppuccin Latte ⇄ Macchiato (remembered) |
| `z` | sleep timer: 15 / 30 / 45 / 60 min / off |
| `d` | download only |
| `/` | search (Esc clears) |
| `r` | refresh library |
| `q` | quit (writes the position first) |

### Media keys (MPRIS)

The player registers on the session bus as `org.mpris.MediaPlayer2.audible_tui`,
so `playerctl` and the keyboard media keys work: play/pause, and next/previous
which skip 15 seconds (same as the arrow keys) instead of a whole chapter. Title and author show up
in `playerctl metadata` and in status-bar media widgets. If several players are
running, `playerctl` picks the first one; use `-p audible_tui` to be explicit.

## Settings (environment variables)

| variable | default |
|---|---|
| `AUDIBLE_TUI_LOCALE` | `it` (also `de`, `fr`, `uk`, `us`, …) |
| `AUDIBLE_TUI_BOOKS` | `~/Audiolibri` |

Books are saved as `<books dir>/<author>/<title> [ASIN].m4b`.

## To do / known gaps

Things still open, to tick off as they get done or verified:

- [ ] **Progress bar / percentage on Audible.** The listening position syncs and
  the book shows up in "Continue listening", but `percent_complete` stays at 0
  in the library, so the official apps show no progress bar. The listening
  events (`StartListening`, `Listening`) are sent in the same format as the web
  player and accepted by the server; it is not known whether they are enough,
  or whether the server recomputes the value very late. Checked about 1 hour
  after playback: still 0.
- [ ] Verify the `MarkAsFinished` event: its format is a guess (never captured
  from an official client), so "finished" may not register.
- [ ] Capture the events of the official mobile app (not only the web player)
  to compare, in case the progress bar is driven by something else.
- [ ] No queue for offline use: position and events are dropped if the network
  is down at that moment, instead of being retried later.
- [ ] No conflict handling: if the position changes on another device while
  you are playing here, the next write overwrites it.
- [ ] Access-token refresh happens only at startup; very long sessions may need
  a restart.
- [ ] Manual "mark as finished / unfinished" from the library.
- [ ] Delete a downloaded book from the app (free disk space).
- [ ] Jump to a chapter from a list, not only previous / next.
- [ ] Volume keys (only the system volume works for now).
- [ ] Remember the playback speed per book.
- [ ] Desktop entry and a floating-window rule for tiling window managers.
- [ ] Automated tests (everything was checked by hand against a real account).

## Notes

- This tool is for listening to audiobooks **you have bought**, on your own
  devices. Downloaded files are decrypted with the key Audible itself hands to
  your registered device; don't share them.
- It uses unofficial, undocumented Audible endpoints through the `audible`
  library; they can change without notice.
- Not affiliated with Audible or Amazon.

## License

AGPL-3.0-or-later, the same as the `audible` library it builds on.
