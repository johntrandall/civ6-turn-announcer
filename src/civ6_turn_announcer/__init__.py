"""Spoken turn alerts for live multiplayer Civilization VI, read from the game's own log files.

The game writes every player's turn state to ``net_message_debug.log`` while a multiplayer game runs.
This module follows that file and tells you three things: a new turn started, you are one of the last
two players still playing, and you are the last one everybody is waiting for.

The module has two halves:

* ``Tracker`` is pure logic. Feed it log lines; it returns ``Event`` objects. It does no input or output,
  so it is what the tests exercise.
* Everything else finds the log folder, follows the file, and turns events into speech, a chime, or a
  desktop notification on the current operating system.
"""

from __future__ import annotations

import argparse
import configparser
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

__version__ = "0.4.0"

MESSAGE_LOG = "net_message_debug.log"
PLAYER_LIST_LOG = "GameCore.log"

# Lines in net_message_debug.log.
_TURN_ACTIVE = re.compile(r"Player (\d+) set TurnActive ([01]),")
_GAME_TURN = re.compile(r"Game Turn: (\d+)")
_END_OF_TURN = "Turn Phase: End of Game Turn"
_PLAYER_NAME = re.compile(r"m_playerID\((\d+)\).*NETWORK_NAME=Char\{([^@}]+)")
# Only this computer's own player produces SEND lines, so they identify who "you" are.
_LOCAL_SEND = re.compile(r"GameCore SEND: \w+: (?:ePlayer|Unit=\d+, Owner)=(\d+)")
# Lines in GameCore.log.
_SLOT_STATUS = re.compile(r"Player (\d+): .*SlotStatus - (\w+)")

NEW_TURN = "new_turn"
TWO_LEFT = "two_left"
ONE_LEFT = "one_left"
ONLY_YOU = "only_you"


@dataclass(frozen=True)
class Event:
    """One thing worth telling the player."""

    kind: str  # NEW_TURN, TWO_LEFT, ONE_LEFT or ONLY_YOU
    text: str  # as shown, with in-game player names
    speech: str  # as spoken, with the spoken-name list applied
    target: Optional[str] = None  # None: for this computer's player. A player name: for that player's computer.


@dataclass
class Tracker:
    """Turns log lines into events.

    ``humans`` is the set of player numbers that are people, not computer players; only their turn state
    counts. ``everyone`` also reports the last two and the last one after this computer's player has
    finished (by default a finished player hears nothing until the next turn). Nothing is reported for a
    game with fewer than two humans unless ``single_player`` is set, so the program can be left running.
    """

    humans: set = field(default_factory=set)
    spoken_names: dict = field(default_factory=dict)
    everyone: bool = False
    single_player: bool = False
    remote_players: set = field(default_factory=set)  # player names announced to on their own computers
    local_player: Optional[int] = None
    names: dict = field(default_factory=dict)
    active: dict = field(default_factory=dict)
    turn: Optional[int] = None
    _awaiting_start: set = field(default_factory=set)
    _new_turn_pending: bool = False
    _last_report: str = ""
    _last_remote: dict = field(default_factory=dict)

    def label(self, player: int) -> str:
        return self.names.get(player, f"Player {player}")

    def _spoken(self, player: int) -> str:
        label = self.label(player)
        return self.spoken_names.get(label, label)

    def still_playing(self) -> list:
        return sorted(player for player in self.humans if self.active.get(player) == 1)

    def feed(self, line: str) -> list:
        """Process one log line and return the events it causes (usually none)."""
        match = _TURN_ACTIVE.search(line)
        if match:
            events = self._turn_active(int(match.group(1)), int(match.group(2)))
            return events if (self.single_player or len(self.humans) >= 2) else []
        if _END_OF_TURN in line:
            # The next time each human goes active is the start of a new turn,
            # not somebody taking a finished turn back.
            self._new_turn_pending = True
            self._awaiting_start = set(self.humans)
            return []
        match = _GAME_TURN.search(line)
        if match:
            self.turn = int(match.group(1))
            return []
        match = _LOCAL_SEND.search(line)
        if match:
            self.local_player = int(match.group(1))
            return []
        if "NetPlayerInfo" in line:
            match = _PLAYER_NAME.search(line)
            if match:
                self.names[int(match.group(1))] = match.group(2)
        return []

    def _turn_active(self, player: int, value: int) -> list:
        if player not in self.humans:
            return []
        self.active[player] = value
        if value == 1 and player in self._awaiting_start:
            # Start of a turn: every human goes active in one burst. Announce the turn once.
            self._awaiting_start.discard(player)
            if self._new_turn_pending:
                self._new_turn_pending = False
                self._last_report = ""
                self._last_remote = {}
                text = f"Turn {self.turn}" if self.turn is not None else "New turn"
                events = [Event(NEW_TURN, text, text)]
                for other in sorted(self.humans):
                    if other != self.local_player and self.label(other) in self.remote_players:
                        events.append(Event(NEW_TURN, text, text, target=self.label(other)))
                return events
            return []
        return self._report_left() + self._report_remote()

    def _report_remote(self) -> list:
        """The same last-two and last-one reports, from the point of view of each remote player."""
        still = self.still_playing()
        if len(still) not in (1, 2):
            return []
        events = []
        for player in still:
            label = self.label(player)
            if player == self.local_player or label not in self.remote_players:
                continue
            if len(still) == 1:
                kind, message = ONLY_YOU, "Only you are left"
            else:
                other = still[0] if still[1] == player else still[1]
                kind, message = TWO_LEFT, f"{self._spoken(other)} and you are left"
            if message != self._last_remote.get(player):
                self._last_remote[player] = message
                events.append(Event(kind, message, message, target=label))
        return events

    def _report_left(self) -> list:
        still = self.still_playing()
        if len(still) not in (1, 2):
            return []  # silent while three or more are playing, so the first finisher is not announced
        local_is_left = self.local_player in still
        if not local_is_left and not self.everyone:
            return []
        others = [player for player in still if player != self.local_player]
        if local_is_left and not others:
            kind, text, speech = ONLY_YOU, "Only you are left", "Only you are left"
        elif local_is_left:
            kind = TWO_LEFT
            text = f"{self.label(others[0])} and you are left"
            speech = f"{self._spoken(others[0])} and you are left"
        elif len(others) == 2:
            kind = TWO_LEFT
            text = f"{self.label(others[0])} and {self.label(others[1])} are left"
            speech = f"{self._spoken(others[0])} and {self._spoken(others[1])} are left"
        else:
            kind = ONE_LEFT
            text = f"{self.label(others[0])} is left"
            speech = f"{self._spoken(others[0])} is left"
        if text == self._last_report:
            return []  # somebody took a turn back and the same people are left again
        self._last_report = text
        return [Event(kind, text, speech)]


def read_humans(player_list_log: Path) -> set:
    """Player numbers whose slot is a person, from the player lists the game writes to GameCore.log.

    The game writes the list several times while a game is set up; the last status of each slot wins.
    """
    status = {}
    try:
        with open(player_list_log, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = _SLOT_STATUS.search(line)
                if match:
                    status[int(match.group(1))] = match.group(2)
    except OSError:
        return set()
    return {player for player, slot in status.items() if slot == "Human"}


def candidate_log_folders() -> list:
    """Where the game keeps its Logs folder, most likely first, for the current operating system."""
    home = Path.home()
    game = "Sid Meier's Civilization VI"
    system = platform.system()
    if system == "Darwin":
        support = home / "Library" / "Application Support" / game
        return [support / "Firaxis Games" / game / "Logs", support / "Logs"]
    if system == "Windows":
        folders = []
        for documents in (home / "Documents", home / "OneDrive" / "Documents"):
            for name in (game, f"{game} (Epic)"):
                folders.append(documents / "My Games" / name / "Logs")
        return folders
    return [
        home / ".local" / "share" / "aspyr-media" / game / "Logs",
        home / ".local" / "share" / "aspyr-media" / game / "Firaxis Games" / game / "Logs",
    ]


def find_log_folder(explicit: Optional[str]) -> Path:
    if explicit:
        folder = Path(explicit).expanduser()
        if not (folder / MESSAGE_LOG).exists():
            raise SystemExit(f"No {MESSAGE_LOG} in {folder}.")
        return folder
    candidates = candidate_log_folders()
    for folder in candidates:
        if (folder / MESSAGE_LOG).exists():
            return folder
    looked = "\n  ".join(str(folder) for folder in candidates)
    raise SystemExit(
        f"Could not find {MESSAGE_LOG}. Start a multiplayer game first, or pass --logs FOLDER.\n"
        f"Looked in:\n  {looked}"
    )


def wait_for_log_folder(explicit: Optional[str]) -> Path:
    """Like find_log_folder, but waits for the game to write its log instead of stopping.

    This is what lets the program run all the time, started at login, before any game exists.
    """
    said = False
    while True:
        try:
            return find_log_folder(explicit)
        except SystemExit:
            if not said:
                print(f"No {MESSAGE_LOG} yet. Waiting for a multiplayer game to start.", flush=True)
                said = True
            time.sleep(5)


SYSTEM_CONFIG = Path("/Library/Application Support/civ6-turn-announcer/config.ini")


def default_config_path() -> Path:
    """The user's settings file; on macOS a computer-wide one is used when the user has none."""
    user = Path.home() / ".config" / "civ6-turn-announcer" / "config.ini"
    if not user.exists() and platform.system() == "Darwin" and SYSTEM_CONFIG.exists():
        return SYSTEM_CONFIG
    return user


def load_config(path: Path) -> tuple:
    """Read the optional settings file: [names], [options], and [remote] sections.

    Returns (names, options, remote). A missing file gives three empty dictionaries.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # player names are case-sensitive
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError:
        return {}, {}, {}
    names = dict(parser["names"]) if parser.has_section("names") else {}
    options = dict(parser["options"]) if parser.has_section("options") else {}
    remote = dict(parser["remote"]) if parser.has_section("remote") else {}
    return names, options, remote


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "yes", "true", "on")


def apply_config(arguments) -> None:
    """Fill in whatever the command line left unset from the settings file. The command line wins."""
    path = Path(arguments.config).expanduser() if arguments.config else default_config_path()
    names, options, remote = load_config(path)
    arguments.name = list(names.items()) + list(arguments.name)
    arguments.remote = list(remote.items()) + list(arguments.remote)
    if arguments.mode is None:
        mode = options.get("mode", "announce").strip().lower()
        arguments.mode = mode if mode in ("announce", "sfx", "silent") else "announce"
    for flag, key in (("everyone", "everyone"), ("notify", "notify"), ("single_player", "single-player")):
        if not getattr(arguments, flag) and _truthy(options.get(key, "")):
            setattr(arguments, flag, True)
    if arguments.logs is None and options.get("logs"):
        arguments.logs = options["logs"]


# --- macOS login item ---------------------------------------------------------------------------------
#
# A bare launchd job shows up in System Settings > Login Items as "sh" or "python". Pointing the job at a
# small app bundle, and naming that bundle in AssociatedBundleIdentifiers, makes macOS list it by name.

APP_NAME = "Civ VI Turn Announcer"
BUNDLE_ID = "io.github.johntrandall.civ6-turn-announcer"
_LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)


def login_item_paths(system: bool) -> tuple:
    """(app bundle, launch agent plist) for one user, or for every user of the computer."""
    if system:
        return Path("/Applications") / f"{APP_NAME}.app", Path("/Library/LaunchAgents") / f"{BUNDLE_ID}.plist"
    home = Path.home()
    return home / "Applications" / f"{APP_NAME}.app", home / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def login_item_files(command: str, app: Path) -> dict:
    """The files of the login item, as {path: bytes}. Pure, so it can be tested."""
    executable = app / "Contents" / "MacOS" / "civ6-turn-announcer-launcher"
    info = {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": executable.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSBackgroundOnly": True,
    }
    quoted = command.replace("'", "'\\''")
    launcher = (
        "#!/bin/sh\n"
        "# Started at login by the launch agent. Output goes to the user's Logs folder.\n"
        'mkdir -p "$HOME/Library/Logs"\n'
        f"exec '{quoted}' >> \"$HOME/Library/Logs/civ6-turn-announcer.log\" 2>&1\n"
    )
    agent = {
        "Label": BUNDLE_ID,
        "ProgramArguments": [str(executable)],
        "AssociatedBundleIdentifiers": [BUNDLE_ID],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "LimitLoadToSessionType": "Aqua",
    }
    return {
        app / "Contents" / "Info.plist": plistlib.dumps(info),
        executable: launcher.encode("utf-8"),
        "agent": plistlib.dumps(agent),
    }


def _launchctl(*arguments: str) -> int:
    return subprocess.run(["launchctl", *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def _console_uid() -> Optional[int]:
    """The user at the screen, or None when nobody is logged in there."""
    try:
        uid = os.stat("/dev/console").st_uid
    except OSError:
        return None
    return uid or None


def install_login_item(system: bool, command: Optional[str]) -> int:
    if platform.system() != "Darwin":
        raise SystemExit("--install-login-item is for macOS. On other systems, start the command from your own startup tools.")
    command = command or shutil.which("civ6-turn-announcer")
    if not command:
        raise SystemExit("Could not find the civ6-turn-announcer command on PATH. Pass --command /full/path/to/it.")
    command = str(Path(command).absolute())
    app, agent_path = login_item_paths(system)
    files = login_item_files(command, app)
    try:
        for path, content in files.items():
            path = agent_path if path == "agent" else path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o755 if path.parent.name == "MacOS" else 0o644)
    except PermissionError as error:
        raise SystemExit(f"{error}\nInstalling for every user of this computer needs sudo.")
    if shutil.which("codesign"):
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(_LSREGISTER):
        subprocess.run([_LSREGISTER, "-f", str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    uid = _console_uid() if system else os.getuid()
    if uid is not None:
        _launchctl("bootout", f"gui/{uid}/{BUNDLE_ID}")
        started = _launchctl("bootstrap", f"gui/{uid}", str(agent_path)) == 0
    else:
        started = False
    print(f"Installed {app}")
    print(f"Installed {agent_path}")
    print("It is running now." if started else "It starts at the next login.")
    print(f'It appears in System Settings > General > Login Items as "{APP_NAME}".')
    print("Its output goes to ~/Library/Logs/civ6-turn-announcer.log")
    return 0


def uninstall_login_item(system: bool) -> int:
    if platform.system() != "Darwin":
        raise SystemExit("--uninstall-login-item is for macOS.")
    app, agent_path = login_item_paths(system)
    uid = _console_uid() if system else os.getuid()
    if uid is not None:
        _launchctl("bootout", f"gui/{uid}/{BUNDLE_ID}")
    try:
        if agent_path.exists():
            agent_path.unlink()
        if app.exists():
            shutil.rmtree(app)
    except PermissionError as error:
        raise SystemExit(f"{error}\nRemoving the computer-wide login item needs sudo.")
    print(f"Removed {agent_path} and {app}")
    return 0


# --- alerts -----------------------------------------------------------------------------------------

_MAC_SOUNDS = {NEW_TURN: "Glass", TWO_LEFT: "Tink", ONE_LEFT: "Pop", ONLY_YOU: "Sosumi"}


def _run_detached(command: list) -> None:
    """Start a command and do not wait for it; a missing program is not an error worth stopping for."""
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def speak(text: str) -> None:
    system = platform.system()
    if system == "Darwin":
        _run_detached(["say", text])
    elif system == "Windows":
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])"
        )
        _run_detached(["powershell", "-NoProfile", "-Command", script, text])
    else:
        for program in ("spd-say", "espeak-ng", "espeak"):
            if shutil.which(program):
                _run_detached([program, text])
                return
        sys.stdout.write("\a")


def chime(kind: str) -> None:
    system = platform.system()
    if system == "Darwin":
        _run_detached(["afplay", f"/System/Library/Sounds/{_MAC_SOUNDS.get(kind, 'Glass')}.aiff"])
    elif system == "Windows":
        import winsound  # only exists on Windows

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION if kind == ONLY_YOU else winsound.MB_OK)
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()


def notify(text: str) -> None:
    """A desktop notification. macOS only; elsewhere the terminal line is the visible record."""
    if platform.system() == "Darwin":
        safe = text.replace("\\", "").replace('"', "")
        _run_detached(["osascript", "-e", f'display notification "{safe}" with title "Civilization VI"'])


_SAFE_HOST = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@-]*$")


def remote_command(text: str) -> str:
    """What runs on the other computer: speak, unless that player runs this program there themselves.

    The [r] keeps the check from matching its own command line.
    """
    safe = re.sub(r"[^A-Za-z0-9 _.,:()-]", "", text)
    return f"pgrep -f 'civ6_turn_announce[r]' >/dev/null || say '{safe}'"


def speak_remote(host: str, text: str) -> None:
    """Speak on another Mac over ssh, without waiting. Needs key-based Remote Login to that Mac."""
    if not _SAFE_HOST.match(host):
        return
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    ssh_folder = Path.home() / ".ssh"
    if ssh_folder.is_dir():
        # Keep one connection open per computer, so each alert does not pay for a new login.
        command += ["-o", "ControlMaster=auto", "-o", f"ControlPath={ssh_folder}/civ6-%C", "-o", "ControlPersist=15m"]
    _run_detached(command + [host, remote_command(text)])


def deliver(event: Event, mode: str, notification: bool, remote_hosts: Optional[dict] = None) -> None:
    if event.target is not None:
        host = (remote_hosts or {}).get(event.target)
        if host:
            print(f"{time.strftime('%H:%M:%S')}  to {event.target} on {host}: {event.text}", flush=True)
            if mode != "silent":
                speak_remote(host, event.speech)
        return
    print(f"{time.strftime('%H:%M:%S')}  {event.text}", flush=True)
    if mode == "announce":
        speak(event.speech)
    elif mode == "sfx":
        chime(event.kind)
    if notification:
        notify(event.text)


# --- following the log --------------------------------------------------------------------------------


def read_lines(handle) -> Iterable[str]:
    """Complete lines available now; a half-written last line is left for the next call."""
    while True:
        position = handle.tell()
        line = handle.readline()
        if not line:
            return
        if not line.endswith(b"\n"):
            handle.seek(position)
            return
        yield line.decode("utf-8", errors="replace")


def new_tracker(folder: Path, arguments) -> Tracker:
    tracker = Tracker(
        humans=read_humans(folder / PLAYER_LIST_LOG),
        spoken_names=dict(arguments.name),
        everyone=arguments.everyone,
        single_player=arguments.single_player,
        remote_players=set(dict(arguments.remote)),
    )
    if arguments.player is not None:
        tracker.local_player = arguments.player
    return tracker


def catch_up(handle, tracker: Tracker, fixed_player: Optional[int]) -> None:
    """Read what the game already wrote, silently, to learn names, the turn, and who is playing now."""
    for line in read_lines(handle):
        tracker.feed(line)
        if fixed_player is not None:
            tracker.local_player = fixed_player


def describe(tracker: Tracker) -> str:
    lines = [f"turn {tracker.turn if tracker.turn is not None else '?'}"]
    for player in sorted(tracker.humans):
        state = {1: "playing", 0: "finished"}.get(tracker.active.get(player), "unknown")
        you = "  (you)" if player == tracker.local_player else ""
        lines.append(f"player {player}  {tracker.label(player)}  {state}{you}")
    if not tracker.humans:
        lines.append("no human players found yet")
    return "\n".join(lines)


def watch(folder: Path, arguments) -> None:
    path = folder / MESSAGE_LOG
    tracker = new_tracker(folder, arguments)
    handle = open(path, "rb")
    catch_up(handle, tracker, arguments.player)
    print(f"Watching {path}")
    print(describe(tracker))
    print("Stop with Ctrl+C.", flush=True)
    try:
        while True:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size < handle.tell():
                # The game started again and began a new log: forget everything and start over.
                handle.close()
                handle = open(path, "rb")
                tracker = new_tracker(folder, arguments)
                catch_up(handle, tracker, arguments.player)
            for line in read_lines(handle):
                if not tracker.humans or _END_OF_TURN in line:
                    # The player list is written once the game is set up, after this program may have started.
                    tracker.humans = read_humans(folder / PLAYER_LIST_LOG) or tracker.humans
                for event in tracker.feed(line):
                    deliver(event, arguments.mode, arguments.notify, dict(arguments.remote))
                if arguments.player is not None:
                    tracker.local_player = arguments.player
            time.sleep(0.25)
    except KeyboardInterrupt:
        print()
    finally:
        handle.close()


def replay(folder: Path, arguments) -> None:
    """Print every event the existing log would have produced, without sound. Useful for checking a setup."""
    tracker = new_tracker(folder, arguments)
    with open(folder / MESSAGE_LOG, "rb") as handle:
        for line in read_lines(handle):
            for event in tracker.feed(line):
                where = f"to {event.target}: " if event.target else ""
                print(f"{where}{event.text}    [spoken: {event.speech}]")
            if arguments.player is not None:
                tracker.local_player = arguments.player


def _name_pair(value: str) -> tuple:
    if "=" not in value:
        raise argparse.ArgumentTypeError("use PLAYER=SPOKEN, for example --name xX_Trajan_Xx=Dave")
    player, spoken = value.split("=", 1)
    return player.strip(), spoken.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="civ6-turn-announcer",
        description="Spoken turn alerts for live multiplayer Civilization VI: a new turn, "
        "the last two players, and the last player everybody is waiting for.",
    )
    parser.add_argument(
        "--mode",
        choices=("announce", "sfx", "silent"),
        default=None,
        help="announce: speak each alert (default). sfx: play a chime. silent: only print.",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        type=_name_pair,
        metavar="PLAYER=SPOKEN",
        help="say SPOKEN in place of the in-game player name PLAYER; repeat for each player",
    )
    parser.add_argument(
        "--remote",
        action="append",
        default=[],
        type=_name_pair,
        metavar="PLAYER=HOST",
        help="also speak PLAYER's alerts on the Mac HOST over ssh (user@host), unless PLAYER runs this program there; repeat for each player",
    )
    parser.add_argument(
        "--everyone",
        action="store_true",
        help="also report the last two and the last one after you have finished your own turn",
    )
    parser.add_argument(
        "--single-player",
        action="store_true",
        help="also announce turns in a game with only one human player (off by default, so it can run all the time)",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="settings file with [names] and [options] sections (default: ~/.config/civ6-turn-announcer/config.ini)",
    )
    parser.add_argument("--notify", action="store_true", help="also show a desktop notification (macOS only)")
    parser.add_argument("--logs", metavar="FOLDER", help="the game's Logs folder, if it is not found automatically")
    parser.add_argument(
        "--player",
        type=int,
        metavar="NUMBER",
        help="your player number, if it is not worked out automatically (see --state)",
    )
    parser.add_argument("--state", action="store_true", help="print the players and who is still playing, then exit")
    parser.add_argument("--replay", action="store_true", help="print the alerts the current log would have produced, then exit")
    parser.add_argument("--test", action="store_true", help="make one test alert in the chosen mode, then exit")
    parser.add_argument(
        "--install-login-item",
        action="store_true",
        help=f'macOS: start at login and keep running, listed in Login Items as "{APP_NAME}"',
    )
    parser.add_argument("--uninstall-login-item", action="store_true", help="macOS: remove the login item")
    parser.add_argument(
        "--system",
        action="store_true",
        help="with the two options above: for every user of this computer (needs sudo)",
    )
    parser.add_argument("--command", metavar="PATH", help="with --install-login-item: the command to start, if it is not on PATH")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[list] = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.install_login_item:
        return install_login_item(arguments.system, arguments.command)
    if arguments.uninstall_login_item:
        return uninstall_login_item(arguments.system)
    apply_config(arguments)
    if arguments.test:
        deliver(Event(NEW_TURN, "Test alert", "Test alert"), arguments.mode, arguments.notify)
        return 0
    if not (arguments.state or arguments.replay):
        watch(wait_for_log_folder(arguments.logs), arguments)
        return 0
    folder = find_log_folder(arguments.logs)
    if arguments.state:
        tracker = new_tracker(folder, arguments)
        with open(folder / MESSAGE_LOG, "rb") as handle:
            catch_up(handle, tracker, arguments.player)
        print(describe(tracker))
        return 0
    replay(folder, arguments)
    return 0
