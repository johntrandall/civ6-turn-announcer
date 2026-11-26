"""Tests of the turn logic, fed with log lines in the format the game writes.

The lines are synthetic (invented player names and ids) but copy the shape of a real four-human
simultaneous-turns game recorded on macOS on 2026-11-25.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from civ6_turn_announcer import (  # noqa: E402
    NEW_TURN,
    ONE_LEFT,
    ONLY_YOU,
    TWO_LEFT,
    Tracker,
    read_humans,
)

STAMP = "[2026-11-25 19:55:21]\t"


def name_line(player, name):
    return (
        f"{STAMP}Net RECV ({player}) :NetPlayerInfo : m_playerID({player}), fromCloud(0), TEAM=Int(-1), "
        f"PLAYER_ID=Int({player}), NETWORK_NAME=Char{{{name}@7656119000000000{player}}}, READY_STATUS=Bool(true)"
    )


def active(player, value):
    return f"{STAMP}Player {player} set TurnActive {value}, TurnActiveCount: 1"


def local_send(player):
    return f"{STAMP}GameCore SEND: PlayerTurnComplete: ePlayer={player}, eReason=0xb6fa1284"


END_OF_TURN = f"{STAMP}Turn Phase: End of Game Turn"


def game_turn(number):
    return f"{STAMP}Game Turn: {number}"


def start_turn(tracker, number, players=(0, 1, 2, 3), computer_players=(4, 5)):
    """The lines the game writes between two turns: end of turn, computer players, then every human at once."""
    events = []
    lines = [END_OF_TURN]
    for player in computer_players:
        lines += [active(player, 1), active(player, 0)]
    lines.append(game_turn(number))
    lines += [active(player, 1) for player in players]
    for line in lines:
        events += tracker.feed(line)
    return events


def four_player_tracker(**options):
    tracker = Tracker(humans={0, 1, 2, 3}, **options)
    for player, name in enumerate(["Alba", "Bruno", "Chidi", "Dana"]):
        tracker.feed(name_line(player, name))
    tracker.feed(local_send(3))  # this computer plays Dana
    return tracker


def kinds(events):
    return [event.kind for event in events]


def texts(events):
    return [event.text for event in events]


class NewTurn(unittest.TestCase):
    def test_new_turn_is_announced_once_with_its_number(self):
        tracker = four_player_tracker()
        events = start_turn(tracker, 12)
        self.assertEqual(texts(events), ["Turn 12"])
        self.assertEqual(kinds(events), [NEW_TURN])

    def test_computer_players_are_ignored(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        self.assertEqual(tracker.feed(active(4, 1)), [])
        self.assertEqual(tracker.feed(active(4, 0)), [])
        self.assertEqual(tracker.still_playing(), [0, 1, 2, 3])


class LastPlayers(unittest.TestCase):
    def test_first_finisher_is_silent(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        self.assertEqual(tracker.feed(active(1, 0)), [])

    def test_you_and_one_other_then_only_you(self):
        tracker = four_player_tracker(spoken_names={"Alba": "Al"})
        start_turn(tracker, 12)
        tracker.feed(active(1, 0))
        events = tracker.feed(active(2, 0))
        self.assertEqual(texts(events), ["Alba and you are left"])
        self.assertEqual(events[0].speech, "Al and you are left")
        self.assertEqual(kinds(events), [TWO_LEFT])
        events = tracker.feed(active(0, 0))
        self.assertEqual(texts(events), ["Only you are left"])
        self.assertEqual(kinds(events), [ONLY_YOU])

    def test_nothing_after_you_have_finished(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        events = []
        for player in (3, 1, 2, 0):
            events += tracker.feed(active(player, 0))
        self.assertEqual(events, [])

    def test_everyone_option_reports_after_you_have_finished(self):
        tracker = four_player_tracker(everyone=True)
        start_turn(tracker, 12)
        tracker.feed(active(3, 0))
        events = tracker.feed(active(1, 0))
        self.assertEqual(texts(events), ["Alba and Chidi are left"])
        events = tracker.feed(active(0, 0))
        self.assertEqual(texts(events), ["Chidi is left"])
        self.assertEqual(kinds(events), [ONE_LEFT])

    def test_taking_a_turn_back_does_not_repeat_the_same_report(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        tracker.feed(active(1, 0))
        self.assertEqual(texts(tracker.feed(active(2, 0))), ["Alba and you are left"])
        self.assertEqual(tracker.feed(active(2, 1)), [])  # Chidi takes the turn back: three playing, silent
        self.assertEqual(tracker.feed(active(2, 0)), [])  # and finishes again: same two as before, silent

    def test_a_different_pair_after_a_turn_is_taken_back_is_reported(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        tracker.feed(active(1, 0))
        tracker.feed(active(2, 0))
        tracker.feed(active(2, 1))
        self.assertEqual(texts(tracker.feed(active(0, 0))), ["Chidi and you are left"])

    def test_next_turn_starts_clean(self):
        tracker = four_player_tracker()
        start_turn(tracker, 12)
        for player in (1, 2, 0, 3):
            tracker.feed(active(player, 0))
        self.assertEqual(texts(start_turn(tracker, 13)), ["Turn 13"])
        tracker.feed(active(1, 0))
        self.assertEqual(texts(tracker.feed(active(2, 0))), ["Alba and you are left"])

    def test_two_player_game_reports_only_you(self):
        tracker = Tracker(humans={0, 1})
        tracker.feed(name_line(0, "Alba"))
        tracker.feed(name_line(1, "Bruno"))
        tracker.feed(local_send(1))
        self.assertEqual(texts(start_turn(tracker, 5, players=(0, 1))), ["Turn 5"])
        self.assertEqual(texts(tracker.feed(active(0, 0))), ["Only you are left"])

    def test_single_player_game_only_announces_turns(self):
        tracker = Tracker(humans={0})
        tracker.feed(local_send(0))
        self.assertEqual(texts(start_turn(tracker, 5, players=(0,))), ["Turn 5"])
        self.assertEqual(tracker.feed(active(0, 0)), [])

    def test_unnamed_player_falls_back_to_a_number(self):
        tracker = Tracker(humans={0, 1, 2}, local_player=2)
        start_turn(tracker, 3, players=(0, 1, 2))
        self.assertEqual(texts(tracker.feed(active(0, 0))), ["Player 1 and you are left"])


class PlayerList(unittest.TestCase):
    def test_last_status_of_each_slot_wins(self):
        import tempfile

        text = (
            "[1.0] Player 0: Civilization - (null) (0)  Leader - (null) (-1), - Level - X, SlotStatus - Human\n"
            "[1.0] Player 1: Civilization - (null) (0)  Leader - (null) (-1), - Level - X, SlotStatus - Human\n"
            "[1.0] Player 2: Civilization - (null) (0)  Leader - (null) (-1), - Level - X, SlotStatus - AI\n"
            "[2.0] Player 1: Civilization - (null) (0)  Leader - (null) (-1), - Level - X, SlotStatus - AI\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "GameCore.log"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(read_humans(path), {0})

    def test_missing_file_gives_no_humans(self):
        self.assertEqual(read_humans(Path("/nonexistent/GameCore.log")), set())


if __name__ == "__main__":
    unittest.main()
