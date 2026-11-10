"""Betting order, raise rules, all-ins, side pots, ties, odd chips.

Seating convention in these tests: the button is the LAST seat, so seat 0 is
the small blind, seat 1 the big blind (3+ players). Blinds are 5/10.
"""
import pytest

from engine.hand import IllegalAction
from engine.table import Table, TableSettings
from helpers import stacked_holdem


def make_table(stacks, holes=None, board=""):
    t = Table(seat_count=len(stacks), settings=TableSettings(1000, 5, 10))
    for i, s in enumerate(stacks):
        t.sit(i, f"P{i}", stack=s)
    holes = holes or ["2c7d", "3c8d", "4c9d", "5cTd", "6cJd", "2h7s"][:len(stacks)]
    t.start_hand(stacked_holdem(holes, board), force_button=len(stacks) - 1)
    return t


def act(t, kind, amount=None):
    t.act(t.hand.actor_seat, kind, amount, seq=t.seq)


# ---------------------------------------------------------------- order
def test_six_handed_blinds_and_action_order():
    t = make_table([1000] * 6)
    h = t.hand
    assert h.bet(0) == 5 and h.bet(1) == 10          # SB, BB
    assert h.actor_seat == 2                           # UTG acts first preflop
    for _ in range(4):                                 # UTG..BTN call
        act(t, "call")
    act(t, "call")                                     # SB completes
    assert h.actor_seat == 1                           # BB gets the option
    act(t, "check")
    assert h.street_name == "Flop"
    assert h.actor_seat == 0                           # SB first after the flop


def test_heads_up_button_posts_small_blind_and_acts_first_preflop():
    t = make_table([1000, 1000])
    h = t.hand
    assert t.button == 1
    assert h.bet(1) == 5 and h.bet(0) == 10
    assert h.actor_seat == 1                           # button first preflop
    act(t, "call"); act(t, "check")
    assert h.actor_seat == 0                           # big blind first postflop


# ---------------------------------------------------------------- sizing
def test_minimum_raise_and_reraise():
    t = make_table([1000] * 3)
    legal = t.hand.legal_actions(2)
    assert (legal.call, legal.min_to, legal.max_to) == (10, 20, 1000)
    act(t, "raise", 30)                                # raise of 20
    legal = t.hand.legal_actions(0)
    assert legal.min_to == 50                          # must raise by >= 20 more
    with pytest.raises(IllegalAction):
        act(t, "raise", 49)
    act(t, "raise", 50)


def test_postflop_bet_must_be_at_least_big_blind():
    t = make_table([1000] * 3)
    act(t, "call"); act(t, "call"); act(t, "check")
    legal = t.hand.legal_actions(0)
    assert legal.raise_kind == "bet" and legal.min_to == 10
    with pytest.raises(IllegalAction):
        act(t, "bet", 9)


def test_short_all_in_does_not_reopen_betting():
    # BB has only 40 total. BTN raises to 30, SB calls, BB shoves 40
    # (a raise of 10 < minimum 20): BTN and SB may only call or fold.
    t = make_table([1000, 40, 1000])
    act(t, "raise", 30); act(t, "call")
    act(t, "raise", 40)
    legal = t.hand.legal_actions(2)
    assert legal.raise_kind is None and legal.call == 10


def test_full_all_in_raise_does_reopen_betting():
    t = make_table([1000, 60, 1000])
    act(t, "raise", 30); act(t, "call")
    act(t, "raise", 60)                     # raise of 30 >= 20: full raise
    assert t.hand.legal_actions(2).raise_kind == "raise"


def test_illegal_moves_rejected():
    t = make_table([1000] * 3)
    with pytest.raises(IllegalAction):      # out of turn
        t.act(0, "call", seq=t.seq)
    with pytest.raises(IllegalAction):      # can't check facing the big blind
        act(t, "check")
    with pytest.raises(IllegalAction):      # non-integer amount
        act(t, "raise", 25.5)
    with pytest.raises(IllegalAction):      # unknown action
        act(t, "teleport")
    stale = t.seq
    act(t, "call")
    with pytest.raises(IllegalAction):      # duplicate/stale request
        t.act(0, "call", seq=stale)
    act(t, "call")
    with pytest.raises(IllegalAction):      # BB can check: folding is refused
        act(t, "fold")


# ---------------------------------------------------------------- pots
def test_side_pots_and_uncalled_bet_returned():
    # P0 (50) has AA, P1 (100) KK, P2 (200) junk. Everyone all-in preflop.
    t = make_table([50, 100, 200], ["AhAd", "KhKd", "7c2d"], "Ts9s3c4h5d")
    act(t, "raise", 200); act(t, "call"); act(t, "call")
    res = t.hand.result
    assert [p["amount"] for p in res["pots"]] == [150, 100]
    assert res["pots"][0]["winners"] == [{"seat": 0, "amount": 150}]
    assert res["pots"][1]["eligible"] == [1, 2]
    assert res["pots"][1]["winners"] == [{"seat": 1, "amount": 100}]
    assert [s.stack for s in t.seats] == [150, 100, 100]   # 100 returned to P2
    assert res["hands"][0]["label"] == "One pair"


def test_split_pot_odd_chip_goes_left_of_button():
    # BTN raises to 30, SB folds (5 dead), BB calls: pot 65. Board is a
    # royal flush so BB and BTN tie; BB is closer to the button's left.
    t = make_table([1000] * 3, ["2c3c", "4d5d", "6h7h"], "AsKsQsJsTs")
    act(t, "raise", 30); act(t, "fold"); act(t, "call")
    for _ in range(3):
        act(t, "check"); act(t, "check")
    res = t.hand.result
    assert res["pots"][0]["amount"] == 65
    assert sorted((w["seat"], w["amount"]) for w in res["pots"][0]["winners"]) \
        == [(1, 33), (2, 32)]
    assert sum(s.stack for s in t.seats) == 3000


def test_folded_player_cannot_win():
    # SB holds the best hand but folds on the flop after putting chips in.
    t = make_table([1000] * 3, ["AhAd", "3c8d", "4c9d"], "AsAc2h7s9c")
    act(t, "call"); act(t, "call"); act(t, "check")
    act(t, "check"); act(t, "bet", 20); act(t, "call")
    act(t, "fold")
    while t.hand_in_progress:
        act(t, "check")
    res = t.hand.result
    assert all(0 not in p["eligible"] for p in res["pots"])
    assert t.seats[0].stack == 990
    assert 0 not in res["hands"]


def test_everyone_folds_early_win_no_cards_shown():
    t = make_table([1000] * 4)
    act(t, "fold"); act(t, "fold"); act(t, "fold")
    res = t.hand.result
    assert not res["showdown"] and res["hands"] == {}
    assert t.seats[1].stack == 1005 and t.seats[0].stack == 995
    assert "everyone else folded" in res["summary"][0]
    assert all(s["cards"] is None for s in t.view(None)["seats"])
