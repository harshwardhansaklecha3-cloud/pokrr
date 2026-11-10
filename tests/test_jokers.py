"""More jokers: deuces wild, one-eyed jacks, real jokers in the deck,
Follow the Queen, wild river, and the Joker auction."""
import random

import pytest

from engine import evaluate as ev
from engine.cards import parse_cards
from engine.hand import IllegalAction
from engine.table import Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant


def table(vid="classic", opts=None, n=2, **add):
    s = TableSettings(1000, 10, 10, vid, tuple(sorted((opts or {}).items())), **add)
    t = Table(seat_count=n, settings=s)
    for i in range(n):
        t.sit(i, f"P{i}")
    return t


def deal(t, holes, board):
    t.start_hand(stacked_variant(t.settings.variant(), holes, board), force_button=len(holes) - 1)
    return t.hand


def check_down(t):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


BOARD = {"flop": "Ks9d4c", "turn": "7h", "river": "Jc"}


def test_deuces_wild_private_and_board():
    t = table(wild="deuces")
    h = deal(t, ["2h2d", "AsAd"], BOARD)
    check_down(t)
    assert h.result["hands"][0]["label"] == "Straight (joker)"    # 2 2 -> Q 10 with K J 9
    v = t.view(0)
    assert "2h" in v["wild_codes"] and "2d" in v["wild_codes"]
    # a deuce on the board is wild for everyone
    t2 = table(wild="deuces")
    h2 = deal(t2, ["KhKd", "AsAd"], dict(BOARD, river="2c"))
    check_down(t2)
    assert h2.result["hands"][0]["label"].startswith("Four of a kind")


def test_one_eyed_jacks_and_suicide_king():
    v = build_variant("classic").with_wild_rule("oneeyed")
    board = {k: parse_cards(x) for k, x in BOARD.items()}
    prep = ev.prepare(v, parse_cards("JhKh"), board)
    assert all(isinstance(c, ev.Wild) for c in prep)
    prep = ev.prepare(v, parse_cards("JdKs"), board)
    assert not any(isinstance(c, ev.Wild) for c in prep)


def test_real_jokers_in_the_deck():
    v = build_variant("classic").with_wild_rule("jokers")
    assert len(v.deck) == 54
    t = table(wild="jokers")
    # P0: joker + Kd on K 9 4 7 J -> the joker makes a third king
    h = deal(t, ["X1Kd", "AsAh"], BOARD)
    assert repr(h.dealt[0][0]) == "X1"
    check_down(t)
    assert h.result["hands"][0]["label"] == "Three of a kind (joker)"
    assert [s.stack for s in t.seats] == [1010, 990]
    assert "X1" in t.view(0)["wild_codes"]
    assert t.view(1)["seats"][0]["cards"] is not None        # shown at showdown


def test_follow_the_queen_changes_wild_rank():
    v = build_variant("classic").with_wild_rule("queen")
    b = {"flop": parse_cards("Qs9d4c"), "turn": parse_cards("7h"), "river": parse_cards("Jc")}
    assert v.global_wilds(b)[0] == {"Q", "9"}                # the card after the queen
    b = {"flop": parse_cards("Qs9d4c"), "turn": parse_cards("Qh"), "river": parse_cards("Jc")}
    assert v.global_wilds(b)[0] == {"Q", "J"}                # a new queen changes it
    b = {"flop": parse_cards("Ks9d4c"), "turn": parse_cards("7h"), "river": parse_cards("Qc")}
    assert v.global_wilds(b)[0] == {"Q"}                     # queen last: only queens


def test_wild_river():
    v = build_variant("classic").with_wild_rule("river")
    b = {"flop": parse_cards("Ks9d4c"), "turn": parse_cards("7h"), "river": []}
    assert v.global_wilds(b)[0] == set()                     # not out yet
    b["river"] = parse_cards("9s")
    assert v.global_wilds(b)[0] == {"9"}


def test_joker_auction_winner_pays_and_gets_a_wild():
    t = table(auction=True, n=3)
    h = deal(t, ["AsAd", "7c2h", "3c4d"], BOARD)
    check_down(t)                                            # preflop + flop -> auction
    assert h.phase_turn and h.phase_turn[0] == "bid"
    first = h.phase_turn[1]
    with pytest.raises(IllegalAction, match="at least"):
        t.phase_action(first, "bid", "5", seq=t.seq)
    t.phase_action(first, "bid", "30", seq=t.seq)
    while h.phase_turn:
        t.phase_action(h.phase_turn[1], "drop", seq=t.seq)
    assert ev.AUCTION_JOKER in h.dealt[first]
    assert t.total_chips() == 3000
    check_down(t)
    assert sum(s.stack for s in t.seats) == 3000


def test_auction_nobody_bids():
    t = table(auction=True)
    h = deal(t, ["AsAd", "7c2h"], BOARD)
    check_down(t)
    while h.phase_turn:
        t.phase_action(h.phase_turn[1], "drop", seq=t.seq)
    assert all(ev.AUCTION_JOKER not in h.dealt[s] for s in h.seat_ids)
    check_down(t)
    assert sum(s.stack for s in t.seats) == 2000


@pytest.mark.parametrize("vid,opts,add", [
    ("classic", {}, {"wild": "jokers"}), ("classic", {"private": "4", "rule": "fix2"}, {"wild": "deuces"}),
    ("pyramid", {}, {"wild": "deuces"}), ("tictactoe", {"private": "4"}, {"wild": "river"}),
    ("redriver", {}, {"wild": "oneeyed"}), ("hilo", {}, {"wild": "oneeyed"}),
    ("classic", {}, {"auction": True, "special_kind": "poison"}), ("poker_patti", {}, {"wild": "deuces"}),
    ("wallstreet", {}, {"wild": "jokers"}), ("floors", {}, {"special_kind": "poison"}),
    ("classic", {}, {"wild": "jokers", "dice": True, "deck": "short"}),
])
def test_wild_games_soak(vid, opts, add):
    from test_soak import ChaosBot, run
    rng = random.Random(8)
    t = Table(seat_count=4, rng=rng, settings=TableSettings(
        300, 10, 10, vid, tuple(sorted(opts.items())), claim=True, **add))
    bots = {}
    for i in range(4):
        t.sit(i, f"P{i}", is_bot=(i >= 2))
        bots[i] = ChaosBot(rng)
    run(t, bots, 10, rng, humans={0, 1})
