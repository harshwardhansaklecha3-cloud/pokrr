import json
import random

import pytest

from engine.hand import IllegalAction
from engine.table import Table, TableSettings
from helpers import stacked_holdem


def table(n=4, stacks=None, seed=3):
    t = Table(seat_count=n, settings=TableSettings(1000, 5, 10), rng=random.Random(seed))
    for i in range(n):
        t.sit(i, f"P{i}", is_bot=i > 0, stack=(stacks or [1000] * n)[i])
    return t


def fold_around(t):
    while t.hand_in_progress:
        legal = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "fold" if legal.fold else "check", seq=t.seq)


def test_button_rotates_and_skips_busted_seats():
    t = table(4, stacks=[1000, 0, 1000, 1000])
    t.start_hand(force_button=0); fold_around(t)
    buttons = [t.button]
    for _ in range(4):
        t.start_hand(); fold_around(t)
        buttons.append(t.button)
    assert buttons == [0, 2, 3, 0, 2]          # seat 1 (busted) never has it
    assert t.view(None)["seats"][1]["status"] == "busted"


def test_cannot_start_with_one_funded_player_and_rebuy_rules():
    t = table(2, stacks=[1000, 0])
    ok, why = t.can_start_hand()
    assert not ok and "players" in why
    with pytest.raises(IllegalAction):
        t.rebuy(0)                              # not busted
    t.rebuy(1)
    assert t.seats[1].stack == 1000 and t.can_start_hand()[0]


def test_settings_change_waits_for_next_hand():
    t = table(3)
    t.start_hand(force_button=2)
    t.change_settings(TableSettings(1000, 50, 100))
    assert t.hand.big_blind == 10
    assert t.view(0)["settings"]["big_blind"] == 10
    assert t.view(0)["pending_settings"]["big_blind"] == 100
    fold_around(t)
    t.start_hand()
    assert t.hand.big_blind == 100


def test_chips_conserved_through_hand_including_mid_hand():
    t = table(3)
    t.start_hand(stacked_holdem(["AhAd", "KhKd", "QhQd"], "2c7s9dTs3h"), force_button=2)
    total = t.total_chips()
    t.act(2, "raise", 300, seq=t.seq)
    assert t.total_chips() == total
    t.act(0, "call", seq=t.seq)
    t.act(1, "call", seq=t.seq)
    assert t.total_chips() == total
    while t.hand_in_progress:
        t.act(t.hand.actor_seat, "check", seq=t.seq)
    assert t.total_chips() == total == 3000


# ---------------------------------------------------------- hidden info
def _all_strings(obj):
    return json.dumps(obj)


def test_view_hides_opponent_cards_and_deck():
    t = table(4)
    t.start_hand(stacked_holdem(["AhAd", "KhKd", "QhQd", "JhJd"], "2c7s9dTs3h"),
                 force_button=3)
    v = t.view(1)
    assert v["seats"][1]["cards"] == ["Kh", "Kd"]
    blob = _all_strings(v)
    for hidden in ("Ah", "Ad", "Qh", "Qd", "Jh", "Jd", "2c", "7s", "9d"):
        assert f'"{hidden}"' not in blob, hidden
    assert "deck" not in v and "shoe" not in blob
    assert all(s["cards"] is None for s in t.view(None)["seats"])   # spectator
    assert v["seats"][0]["card_count"] == 2                         # backs only


def test_folded_cards_stay_hidden_after_showdown():
    t = table(3)
    t.start_hand(stacked_holdem(["AhAd", "KhKd", "QhQd"], "2c7s9dTs3h"), force_button=2)
    t.act(2, "fold", seq=t.seq)          # QQ folds
    t.act(0, "call", seq=t.seq)
    t.act(1, "check", seq=t.seq)
    while t.hand_in_progress:
        t.act(t.hand.actor_seat, "check", seq=t.seq)
    v = t.view(0)
    assert v["seats"][1]["cards"] == ["Kh", "Kd"]     # showdown reveal
    assert v["seats"][2]["cards"] is None              # folded: never shown
    assert '"Qh"' not in _all_strings(v)
    assert v["result"]["hands"][0]["label"] == "One pair"
    assert set(v["result"]["hands"]) == {0, 1}
    # Regression: the LOSING hand must be explained with its own hole cards
    # (KK), not just the board.
    loser = v["result"]["hands"][1]
    assert loser["label"] == "One pair" and {"Kh", "Kd"} <= set(loser["cards"])
    assert v["seats"][1]["status"] == "in"
    # Regression: the loser still sees their own cards after the hand.
    assert t.view(1)["seats"][1]["cards"] == ["Kh", "Kd"]


def test_legal_actions_only_sent_to_actor():
    t = table(3)
    t.start_hand(force_button=2)
    assert t.view(2)["legal"] is not None
    assert t.view(0)["legal"] is None and t.view(None)["legal"] is None
