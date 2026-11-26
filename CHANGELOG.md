# Changelog

## 0.3.0 (2026-11-25)

- macOS: `--install-login-item` starts it at login and keeps it running, listed in System Settings, Login Items as "Civ VI Turn Announcer"; `--uninstall-login-item` removes it; `--system` does either for every user of the computer.
- macOS: a computer-wide settings file, `/Library/Application Support/civ6-turn-announcer/config.ini`, used by a user who has none of their own.

## 0.2.0 (2026-11-25)

Made to be left running.

- Waits for a game when none has been started, where 0.1 stopped with an error.
- Silent in a game with fewer than two human players, unless `--single-player` is given. This changes 0.1, which announced turns in single-player games.
- Settings file `~/.config/civ6-turn-announcer/config.ini` for spoken names and options; `--config FILE` to use another.
- Homebrew: `brew services start johntrandall/tap/civ6-turn-announcer`.

## 0.1.1 (2026-11-25)

- Published to PyPI and to the `johntrandall/tap` Homebrew tap; the README install lines now use them. No change to behavior.

## 0.1.0 (2026-11-25)

First release.

- Announces a new turn, "X and you are left" when you are one of the last two players, and "Only you are left" when everybody is waiting for you.
- Three modes: `announce` (spoken), `sfx` (chimes), and `silent` (terminal only).
- Spoken names for players with `--name PLAYER=SPOKEN`.
- `--everyone`, `--notify`, `--state`, `--replay`, and `--test`.
- Tested on macOS with the Steam edition in a live four-player game. Windows and Linux support is written but not tested.
