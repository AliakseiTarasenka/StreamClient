"""Upstream JSON parsing contracts and useful errors for malformed structures."""

import json

import pytest

from src.application.parsers.event_parser import GameEventParser
from src.application.parsers.game_parser import GameParser


def test_scoring_events_use_both_rosters_and_latest_timestamp():
    state = GameEventParser.parse_event_data(
        json.dumps(
            {
                "game_id": 42,
                "ts": {"time": 500, "ds": 100, "stop": False},
                "h": 0,
                "a": 0,
                "hn": "Home",
                "ha": "H",
                "an": "Away",
                "aa": "A",
                "p": {"h": {"7": "Home scorer"}, "a": {"8": "Away scorer", "9": "Assist"}},
                "e": [
                    {"t": 30, "e": "a", "y": "S", "s": 8, "a": 9, "hs": 1, "as": 2},
                    {"t": 10, "e": "h", "y": "S", "s": "7", "hs": 1, "as": 0},
                    {"y": "T"},
                ],
            }
        )
    )
    assert state.game_id == 42
    assert (state.game_time, state.game_stopwatch_timestamp, state.game_stopped) == (
        500,
        100,
        False,
    )
    assert (state.home_team_name, state.home_team_abbr) == ("Home", "H")
    assert (state.away_team_name, state.away_team_abbr) == ("Away", "A")
    assert len(state.events) == 2
    assert state.events[1].scorer == "Home scorer"
    assert state.events[1].assist is None
    assert (state.latest_scorer, state.latest_assist) == ("Away scorer", "Assist")
    assert (state.home_score, state.away_score) == ("1", "2")


def test_missing_fields_defaults_unknown_players_and_empty_event_scores():
    state = GameEventParser.parse_event_data("{}")
    assert state.game_id == 0
    assert state.game_stopped is True
    assert state.game_time is None
    assert state.events == []
    assert state.home_players == state.away_players == {}
    assert state.home_score == state.away_score == "0"
    state = GameEventParser.parse_event_data(
        '{"h": 3, "a": 4, "e": [{"t": 1, "e": "h", "y": "S", "s": 999}]}'
    )
    assert state.latest_scorer is None
    assert state.latest_assist is None
    assert (state.home_score, state.away_score) == ("3", "4")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "Failed to decode JSON"),
        ("[]", "response must be an object"),
        ('{"ts": null}', "ts must be an object"),
        ('{"p": []}', "p must be an object"),
        ('{"p": {"h": null}}', "p.h must be an object"),
        ('{"p": {"a": {"7": 42}}}', "p.a must map"),
        ('{"e": null}', "e must be an array"),
        ('{"e": [null]}', r"e\[0\] must be an object"),
        ('{"e": [{"y": "S", "e": "h"}]}', r"e\[0\].t must be an integer"),
        ('{"e": [{"y": "S", "t": true, "e": "h"}]}', "integer scoring timestamp"),
        ('{"e": [{"y": "S", "t": 1}]}', r"e\[0\].e must be a nonempty team"),
    ],
)
def test_event_parser_rejects_malformed_json_and_nested_shapes(payload, message):
    with pytest.raises(ValueError, match=message):
        GameEventParser.parse_event_data(payload)


def test_schedule_parses_entries_and_skips_missing_required_fields(capsys):
    payload = {
        "i": 42,
        "d": "2026-10-24",
        "t": "12:00",
        "hn": "Home",
        "ha": "H",
        "an": "Away",
        "aa": "A",
        "e": False,
        "dv": "Open",
    }
    games = GameParser.parse(json.dumps([payload, {}]))
    assert len(games) == 1
    game = games[0]
    assert game.game_id == 42
    assert (game.date, game.time) == ("2026-10-24", "12:00")
    assert (game.home_team, game.away_team) == ("Home", "Away")
    assert (game.home_score, game.away_score) == ("TBD", "TBD")
    assert game.division == "Open"
    assert game.is_finished is False
    assert "missing required attribute" in capsys.readouterr().out
    assert GameParser.parse("  ") == []


@pytest.mark.parametrize("payload", ["{", "{}", "null"])
def test_schedule_rejects_invalid_json_or_non_array(payload):
    with pytest.raises(ValueError):
        GameParser.parse(payload)
