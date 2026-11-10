"""Joker, Poison and Jumping-joker cards, plus 3or3or2 and bot levels.

Seating as elsewhere: button is the last seat; blinds 10/10; check down.
"""
import random

import pytest

from bots import BasicBot
from engine import evaluate as ev
from engine.cards import parse_cards
from engine.table import Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant


def special_table(preset, kind, stage, holes, board, options=None, bots=()):
    opts = tuple(sorted((options or {}).items()))
    n = len(holes)
    t = Table(seat_count=n, settings=TableSettings(1000, 10, 10, preset, opts, kind, stage))
    for i in range(n):
        t.sit(i, f"P{i}", is_bot=i in bots)
    v = build_variant(preset, options).with_special(kind, stage)
    t.start_hand(stacked_variant(v, holes, board), force_button=n - 1)
    return t


def check_down(t):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


def stacks(t):
    return [s.stack for s in t.seats]


BOARD = {"flop": "Ks9d4c", "turn": "2h", "river": "Jc"}


# ------------------------------------------------------------ wild evaluation
def test_one_wild_makes_the_best_possible_hand():
    w = ev.Wild(parse_cards("7c")[0])
    hand = ev.score5(tuple(parse_cards("AsKsQsJs")) + (w,))
    assert hand.entry.label.value == "Straight flush"          # wild = Ts -> royal
    hand = ev.score5(tuple(parse_cards("9h9d9c2s")) + (w,))
    assert hand.entry.label.value == "Four of a kind"          # no five of a kind


def test_many_wilds_fall_back_to_straight_flush():
    ws = tuple(ev.Wild(c) for c in parse_cards("7c7d7h7s"))
    assert ev.score5(ws + tuple(parse_cards("2d"))).entry.label.value == "Straight flush"


# ------------------------------------------------------------ joker
def test_joker_makes_private_cards_of_its_rank_wild():
    # Joker turned up at the river is a 7. P0 holds 7c 3d -> 7c is wild.
    # P0: 7c (wild) + Qd on K 9 4 2 J -> wild plays as a 10: K-Q-J-10-9 straight.
    board = dict(BOARD, special="7h")
    t = special_table("holdem", "joker", "River", ["7cQd", "AhAd"], board)
    v = t.hand.variant
    assert any(g.id == "special" for g in v.board_groups)
    assert all("special" not in r.groups for r in v.rows)       # not part of any row
    check_down(t)
    res = t.hand.result
    assert res["hands"][0]["label"] == "Straight (joker)"
    assert "7c" in res["hands"][0]["cards"]                    # shown as the real card
    assert stacks(t) == [1010, 990]                           # beats pocket aces


def test_joker_does_not_make_board_cards_wild():
    # Joker is a 9; the 9d on the BOARD stays a normal 9.
    board = dict(BOARD, special="9h")
    t = special_table("holdem", "joker", "River", ["3c3d", "AhAd"], board)
    check_down(t)
    assert "(joker)" not in t.hand.result["hands"][0]["label"]
    assert stacks(t) == [990, 1010]


def test_joker_before_it_is_turned_up_does_nothing():
    v = build_variant("holdem").with_special("joker", "River")
    hole = parse_cards("7c3d")
    board = {"flop": parse_cards("Ks9d4c"), "turn": parse_cards("2h"), "river": [], "special": []}
    assert not any(isinstance(c, ev.Wild) for c in ev.prepare(v, hole, board))


# ------------------------------------------------------------ poison
def test_poison_private_cards_cannot_be_used():
    # Poison is a K at the flop. P0 holds KhKd (pocket kings!) -> useless.
    board = dict(BOARD, special="Kc")
    t = special_table("holdem", "poison", "Flop", ["KhKd", "3c2c"], board)
    check_down(t)
    res = t.hand.result
    assert "Kh" not in res["hands"][0]["cards"] and "Kd" not in res["hands"][0]["cards"]
    # P0 plays the board (K-high), P1 has a pair of 2s -> P1 wins.
    assert stacks(t) == [990, 1010]


def test_poison_with_fix2_can_leave_no_legal_hand():
    board = dict(BOARD, special="Kc")
    t = special_table("holdem", "poison", "Flop", ["Kh5d", "3c8c"], board,
                      options={"hand_rule": "fix2"})
    check_down(t)
    res = t.hand.result
    assert res["hands"][0]["label"] == "No legal hand"
    assert stacks(t) == [990, 1010]


def test_human_cannot_declare_a_poisoned_card():
    # Pyramid + poison: the human may not pick the poisoned card.
    board = {"t5": "AsAhAdAc2s", "t4": "KsKhKdKc", "t3": "Qs9h8d", "t2": "7c6c", "t1": "3d",
             "special": "Js"}
    t = special_table("pyramid", "poison", "River", ["JdTs", "5h4h"], board, bots=(1,))
    check_down(t)
    from engine.hand import IllegalAction
    with pytest.raises(IllegalAction, match="poisoned"):
        t.declare(0, {"main": {"hole": ["Jd", "Ts"], "board": ["As", "Ks", "Qs"]}}, seq=t.seq)
    t.declare(0, {"main": {"hole": ["Ts"], "board": ["As", "Ks", "Qs", "7c"]}}, seq=t.seq)
    assert not t.hand_in_progress


# ------------------------------------------------------------ jumping joker
def test_jumping_joker_poison_rank_and_neighbours_wild():
    v = build_variant("holdem").with_special("jumping", "River")
    board = {"flop": parse_cards("Ks9d4c"), "turn": parse_cards("2h"), "river": parse_cards("Jc"),
             "special": parse_cards("7h")}
    prep = ev.prepare(v, parse_cards("7c8d"), board)      # 7 = poison, 8 = wild
    assert len(prep) == 1 and isinstance(prep[0], ev.Wild)
    prep = ev.prepare(v, parse_cards("6s3d"), board)      # 6 = wild, 3 normal
    assert isinstance(prep[0], ev.Wild) and not isinstance(prep[1], ev.Wild)
    # Ace wraps: poison A -> K and 2 are wild
    board["special"] = parse_cards("Ad")
    prep = ev.prepare(v, parse_cards("Kc2c"), board)
    assert all(isinstance(c, ev.Wild) for c in prep)


@pytest.mark.parametrize("preset", ["holdem", "omaha", "pyramid", "elevator",
                                    "two_or_three", "three_three_two", "double_holdem"])
@pytest.mark.parametrize("kind", ["joker", "poison", "jumping"])
def test_special_cards_work_in_every_variation(preset, kind):
    """Random full hands (bots + 1 'human' who declares) stay legal and
    conserve chips with each special card."""
    from test_soak import ChaosBot, run
    rng = random.Random(hash((preset, kind)) % 997)
    t = Table(seat_count=3, rng=rng, settings=TableSettings(300, 10, 10, preset, (), kind,
                                                             rng.choice(["Flop", "Turn", "River"])))
    bots = {}
    for i in range(3):
        t.sit(i, f"P{i}", is_bot=(i != 0))
        bots[i] = ChaosBot(rng)
    run(t, bots, 8, rng, humans={0})


# ------------------------------------------------------------ 3or3or2
def test_three_three_two_rows_and_best_row_wins():
    board = {"flop1": "AsKsQs", "flop2": "2c3c4c", "flop3": "9d9h", "turn": "7h",
             "river1": "8h", "river2": "Kd", "river3": "Td"}
    # P0: JsTs -> row 1 royal flush. P1: 9s9c... row 3 uses exactly 3: 9s9c + 5d
    t = special_table.__wrapped__ if False else None
    tb = Table(seat_count=2, settings=TableSettings(1000, 10, 10, "three_three_two"))
    tb.sit(0, "P0"); tb.sit(1, "P1")
    v = build_variant("three_three_two")
    tb.start_hand(stacked_variant(v, ["JsTs2d3d4d", "9s9c5d6d7d"], board), force_button=1)
    check_down(tb)
    res = tb.hand.result
    p0 = {r["row"]: r for r in res["hands"][0]["rows"]}
    p1 = {r["row"]: r for r in res["hands"][1]["rows"]}
    assert p0["r1"]["label"] == "Royal flush"
    assert p1["r3"]["label"] == "Four of a kind"           # 9s9c + 9d9h + one more
    assert len(p1["r3"]["hole_used"]) == 3 and len(p0["r1"]["hole_used"]) == 2
    assert stacks(tb) == [1010, 990]


# ------------------------------------------------------------ bot levels
@pytest.mark.parametrize("level", ["noob", "amateur", "tycoon"])
def test_every_bot_level_plays_legally(level):
    from test_soak import run
    rng = random.Random(3)
    t = Table(seat_count=3, settings=TableSettings(500, 10, 10, "holdem"), rng=rng)
    bots = {}
    for i in range(3):
        t.sit(i, f"B{i}", is_bot=True, bot_level=level)
        bots[i] = BasicBot(random.Random(i), samples=20, level=level)
    run(t, bots, 10, rng)


def test_tycoon_folds_junk_more_than_noob_calls():
    """Facing a big bet with 7-2 offsuit on a dry board, the tycoon folds
    while the noob often calls."""
    from engine.variants import HOLDEM
    view = {"legal": {"fold": True, "check": False, "call": 200, "raise_kind": "raise",
                      "min_to": 400, "max_to": 1000},
            "you": 0, "total_pot": 260, "stage": "Flop",
            "board": {"flop": ["As", "Kd", "Qh"], "turn": [], "river": []},
            "seats": [{"index": 0, "empty": False, "cards": ["7c", "2d"], "status": "in",
                       "bet": 0, "stack": 1000, "is_button": False},
                      {"index": 1, "empty": False, "cards": None, "status": "in",
                       "bet": 200, "stack": 800, "is_button": False}]}
    def fold_rate(level):
        folds = 0
        for k in range(40):
            bot = BasicBot(random.Random(k), samples=60, level=level)
            folds += bot.decide(view, HOLDEM)[0] == "fold"
        return folds / 40
    assert fold_rate("tycoon") > 0.9
    assert fold_rate("noob") < fold_rate("tycoon")
