"""What jokers play as, and the private 'learn from this hand' notes."""
import json

from engine.cards import parse_cards
from engine.table import Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant

BOARD = {"flop": "Ks9d4c", "turn": "2h", "river": "Jc"}


def check_down(t):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


def make(preset, holes, board, special=None, options=None, bots=()):
    opts = tuple(sorted((options or {}).items()))
    kind, stage = special or ("none", "River")
    s = TableSettings(1000, 10, 10, preset, opts, kind, stage)
    t = Table(seat_count=len(holes), settings=s)
    for i in range(len(holes)):
        t.sit(i, f"P{i}", is_bot=i in bots)
    v = s.variant()
    t.start_hand(stacked_variant(v, holes, board), force_button=len(holes) - 1)
    return t


def test_joker_shows_what_it_plays_as():
    t = make("holdem", ["7cQd", "AhAd"], dict(BOARD, special="7h"), ("joker", "River"))
    check_down(t)
    row = t.hand.result["hands"][0]["rows"][0]
    assert row["label"] == "Straight (joker)"
    jok = [p for p in row["played"] if p["joker"]]
    assert len(jok) == 1 and jok[0]["joker"] == "7c" and jok[0]["code"][0] == "T"   # 7c plays as a 10
    assert "7c plays as T" in row["joker_text"]


def test_lessons_explain_loss_and_are_private():
    # P0 (human) has a pair of 2s, P1 (human) has trips: P0 should learn why.
    t = make("holdem", ["2c3d", "KhKd"], BOARD)
    check_down(t)
    l0, l1 = t.view(0)["lessons"], t.view(1)["lessons"]
    assert any("Three of a kind" in x and "beat your" in x and "ranks above" in x for x in l0)
    assert any(x.startswith("You won") for x in l1)
    # privacy: P1's notes never appear in P0's view and vice versa
    assert json.dumps(l1) not in json.dumps(t.view(0))
    assert t.view(None)["lessons"] == []


def test_lessons_for_a_fold_say_what_would_have_happened():
    # P0 folds pocket kings to a raise; with this board KK would have made
    # trips and beaten P1's pair of 2s at the showdown.
    t = make("holdem", ["KhKd", "2c3d", "7s8s"], BOARD, bots=(2,))
    t.act(2, "raise", 100, seq=t.seq)          # button raises
    t.act(0, "fold", seq=t.seq)                 # P0 folds KK
    t.act(1, "call", seq=t.seq)
    check_down(t)
    lessons = t.view(0)["lessons"]
    assert any("You folded on the preflop holding Kh Kd" in x for x in lessons)
    assert any("Three of a kind" in x for x in lessons)
    assert any("would have WON" in x and "folding cost you" in x for x in lessons)


def test_pyramid_better_choice_is_pointed_out():
    board = {"t5": "AsAhAdAc2s", "t4": "KsKhKdKc", "t3": "Qs9h8d", "t2": "7c6c", "t1": "3d"}
    t = make("pyramid", ["JsTs", "5h4h"], board, bots=(1,))
    check_down(t)
    t.declare(0, {"main": {"hole": ["Js", "Ts"], "board": ["Ah", "Kh", "9h"]}}, seq=t.seq)
    lessons = t.view(0)["lessons"]
    assert any(x.startswith("Better choice") and "Royal flush" in x and "WON" in x for x in lessons)
