# civ6-turn-announcer

Spoken turn alerts for live multiplayer Civilization VI. It tells you when a new turn starts, when you are one of the last two players still playing, and when you are the last one everybody is waiting for. It reads the game's own log files, so it needs no mod and changes nothing in the game.

**Tested on macOS only so far.** Windows and Linux support is written but has not been run; see [What has been tested](#what-has-been-tested). Reports from either are welcome.

It is for people who play simultaneous-turn multiplayer with friends or family and look away between turns: at another window, at a phone, or at dinner.

## What it says

| When | Spoken alert |
|---|---|
| A new turn starts | "Turn 27" |
| You and one other player are still playing | "Priya and you are left" |
| You are the only one still playing | "Only you are left" |

It stays quiet the rest of the time. Nothing is said while three or more players are still playing, so the first player to finish is not announced. Once you have ended your own turn you hear nothing until the next turn starts. If someone takes a finished turn back and then finishes again, the same alert is not repeated.

Each player can run it on their own computer and hear only their own alerts. Or one Mac in the house can run it and speak each player's alerts on that player's Mac; see [One Mac for the whole household](#one-mac-for-the-whole-household).

## Install

It needs Python 3.9 or later and has no other dependencies.

On any system, with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```
uv tool install civ6-turn-announcer
```

```
pipx install civ6-turn-announcer
```

On a Mac you can use [Homebrew](https://brew.sh/) instead, which brings its own Python:

```
brew install johntrandall/tap/civ6-turn-announcer
```

To try it once without installing:

```
uvx civ6-turn-announcer --test
```

## Use

Start or join a multiplayer game, then run this in a terminal and leave it running:

```
civ6-turn-announcer
```

It prints the players it found and which one is you, then speaks each alert and prints it with the time. Stop it with Ctrl+C. If no game has been started yet, it waits for one.

### Leave it running

It is built to run all the time. With no game open it waits; when the game starts a new log it starts over by itself. It stays silent in a game with only one human player, so single-player turns are not read aloud (add `--single-player` if you want them).

On a Mac, one command makes it start at login and stay running:

```
civ6-turn-announcer --install-login-item
```

It appears in System Settings, General, Login Items as "Civ VI Turn Announcer", where you can switch it off. Its output goes to `~/Library/Logs/civ6-turn-announcer.log`. Remove it with `--uninstall-login-item`.

What that installs: a very small app, `~/Applications/Civ VI Turn Announcer.app`, which only starts the command, and a launch agent, `~/Library/LaunchAgents/io.github.johntrandall.civ6-turn-announcer.plist`, which starts the app at login. The app exists so macOS lists the job under its own name and not as "sh" or "python". Add `--system` (with `sudo`) to install for every user of the computer, into `/Applications` and `/Library/LaunchAgents`.

`brew services start johntrandall/tap/civ6-turn-announcer` also works, without the named Login Items entry.

### One Mac for the whole household

One Mac that is in the game can speak for everybody. It already knows every player's turn state, so it sends each player's alerts to that player's own Mac over the local network.

```
civ6-turn-announcer --remote MoonlitLlama=priya@priyas-macbook.local --remote xX_Trajan_Xx=dave@daves-imac.local
```

The left side is the in-game player name; the right side is where that player sits, as `user@host`. Each of those players then hears "Turn 27", "Dave and you are left", and "Only you are left" on their own Mac, and nothing once they have finished, the same as if they ran it themselves.

- **A player's own copy wins.** If a player runs this program on their own Mac, the central Mac stays silent for them there, so nobody hears an alert twice.
- **What it needs.** Remote Login (System Settings, General, Sharing) switched on at each of those Macs, and an ssh key from the central Mac's user accepted there, so `ssh user@host` works without a password. Nothing has to be installed on them.
- **How it speaks.** It runs the Mac's built-in `say` command there. The other Macs must be Macs; the central one too.
- **Limits.** A Mac that is asleep or off the network is skipped silently. The player of the central Mac needs no entry; players without an entry get nothing.

### Settings file

Options can live in `~/.config/civ6-turn-announcer/config.ini`, which is how you set spoken names when the program runs at login. Anything given on the command line wins. On a Mac, a user without that file gets `/Library/Application Support/civ6-turn-announcer/config.ini` if it exists, for settings shared by every user of the computer.

```
[names]
xX_Trajan_Xx = Dave
MoonlitLlama = Priya

[options]
mode = announce
everyone = no
notify = no
single-player = no

[remote]
MoonlitLlama = priya@priyas-macbook.local
```

### Spoken names

In-game player names are often account names that a voice reads badly. Give each one a spoken name:

```
civ6-turn-announcer --name xX_Trajan_Xx=Dave --name MoonlitLlama=Priya
```

The left side is the player name exactly as the game shows it; `--state` lists them.

### Options

| Option | What it does |
|---|---|
| `--mode announce` | Speak each alert. This is the default. |
| `--mode sfx` | Play a short chime in place of the voice, a different one for each kind of alert. |
| `--mode silent` | Only print the alerts in the terminal. |
| `--name PLAYER=SPOKEN` | Say SPOKEN in place of the in-game name PLAYER. Repeat for each player. |
| `--single-player` | Also announce turns in a game with only one human player. |
| `--config FILE` | Read settings from FILE in place of `~/.config/civ6-turn-announcer/config.ini`. |
| `--install-login-item`, `--uninstall-login-item` | macOS: start at login under the name "Civ VI Turn Announcer", or remove that. `--system` does it for every user (needs `sudo`); `--command PATH` names the command to start if it is not on PATH. |
| `--remote PLAYER=HOST` | Also speak PLAYER's alerts on the Mac HOST (`user@host`) over ssh, unless PLAYER runs this program there. Repeat for each player. |
| `--everyone` | Also report the last two and the last one after you have finished your own turn ("Priya and Dave are left", "Dave is left"). |
| `--notify` | Also show a desktop notification. macOS only. |
| `--state` | Print the players, which one is you, and who is still playing, then exit. |
| `--replay` | Print the alerts the current log would have produced, without sound, then exit. A quick way to check a setup. |
| `--test` | Make one test alert in the chosen mode, then exit. |
| `--logs FOLDER` | The game's `Logs` folder, if it is not found automatically. |
| `--player NUMBER` | Your player number, if it is not worked out automatically. |

## What has been tested

| Platform | Status |
|---|---|
| macOS, Steam edition | Tested in a live four-player simultaneous-turns game, November 2026. |
| Windows | Not tested. The log folder locations and the speech command are written from documentation. Reports are welcome. |
| Linux | Not tested. Speech uses `spd-say`, `espeak-ng`, or `espeak` if one is installed. |

Also not tested: hot seat, Play by Cloud, dynamic or sequential turn modes, and games with teams. The login item has been run on macOS 15; `brew services` has not been tried. Speaking on other Macs has been run between Macs on one home network.

If it does not find the game's logs it lists the folders it looked in. Please open an issue with the folder where your `net_message_debug.log` lives.

## How it works

While a multiplayer game runs, Civilization VI appends to `net_message_debug.log` in its `Logs` folder. Three kinds of line matter:

- `Player 2 set TurnActive 0` means player 2 ended their turn, and `TurnActive 1` means they are playing (at the start of a turn, or because they took a finished turn back).
- `Turn Phase: End of Game Turn` and `Game Turn: 27` mark the change from one turn to the next.
- `GameCore SEND:` lines are written only for the player on this computer, which is how the program knows who "you" are.

Player names come from the `NetPlayerInfo` lines in the same file. Which players are people and which are computer players comes from the player list in `GameCore.log`.

The log format is not documented by the game's makers and could change in an update. The turn logic lives in one small class with tests, so a format change should be a small fix.

On macOS the folder is `~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs`.

## Development

```
git clone https://github.com/johntrandall/civ6-turn-announcer
cd civ6-turn-announcer
python3 -m unittest discover -s tests
```

## License and disclaimer

MIT; see [LICENSE](https://github.com/johntrandall/civ6-turn-announcer/blob/main/LICENSE).

This is an independent project. It is not affiliated with or endorsed by Firaxis Games, 2K, Take-Two Interactive, or Aspyr. Sid Meier's Civilization is a trademark of its owners.
