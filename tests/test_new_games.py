"""Rules of the November games: Pineapple/Irish, Dice, Red River, Short Deck,
Royal, Omaha Hi-Lo, Courchevel, Iron Cross, Chowaha, Blackjack Hold'em,
Wall Street and the 7-2 bounty. Seating: button is the last seat."""
import random

import pytest

from engine import evaluate as ev
from engine.cards import parse_cards
from engine.hand import IllegalAction
from engine.table import BOUNTY_BB, Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant


def table(vid, opts=None, n=2, bots=(), stack=1000, **add):
    s = TableSettings(stack, 10, 10, vid, tuple(sorted((opts or {}).items())), **add)
    t = Table(seat_count=n, settings=s)
    for i in range(n):
        t.sit(i, f"P{i}", is_bot=i in bots)
    return t


def deal(t, holes, board, button=None):
    v = t.settings.variant()
    t.start_hand(stacked_variant(v, holes, board), force_button=len(holes) - 1 if button is None else button)
    return t.hand


def check_down(t, until=None):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        if until and until(t.hand):
            return
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


def stacks(t):
    return [s.stack for s in t.seats]


# ------------------------------------------------------------ Pineapple / Irish
def test_irish_throws_away_two_after_the_flop():
    t = table("classic", {"private": "4", "rule": "any"}, pineapple="flop", pine_count=2)
    h = deal(t, ["AsAdKc2h", "7c7d3s4h"], {"flop": "Ah9c2d", "turn": "5s", "river": "Jd"})
    check_down(t, until=lambda h: h.street_name == "Flop")
    check_down(t)                                         # flop betting -> throw away
    assert h.pass_awaiting == {0, 1}
    with pytest.raises(IllegalAction):
        t.pass_card(0, "Jd", seq=t.seq)                    # not your card
    t.pass_card(0, "Kc", seq=t.seq)
    t.pass_card(0, "2h", seq=t.seq)
    t.pass_card(1, "3s", seq=t.seq)
    t.pass_card(1, "4h", seq=t.seq)
    assert len(h.dealt[0]) == 2 and len(h.discarded[0]) == 2
    check_down(t)
    assert h.result["hands"][0]["label"] == "Three of a kind"     # AsAd + Ah
    assert stacks(t) == [1010, 990]


def test_pineapple_too_many_throws_deals_extra_cards():
    # Fix 2 with 3 throws: deal 3 extra so exactly 2 are left to play
    v = table("classic", {"private": "2", "rule": "fix2"}, pineapple="every").settings.variant()
    assert v.hole_card_count == 5                         # 5 - 3 thrown = exactly 2 to play


# ------------------------------------------------------------ Dice
def test_dice_replaces_the_rolled_card_then_bets_again():
    t = table("classic", dice=True)
    h = deal(t, ["AsAd", "7c2h"], {"flop": "Kh9c3d", "turn": "5s", "river": "Jd", "dice": "Ah"})
    h.dice_roller = lambda: 4                             # 4th card (the turn 5s) -> Ah
    check_down(t, until=lambda h: h.street_name == "Dice")
    assert h.board_cards()["turn"] == parse_cards("Ah")
    assert h.dice_rolls[0]["old"] == "5s" and h.dice_rolls[0]["new"] == "Ah"
    assert h.street_name == "Dice" and h.actor_seat is not None    # a betting round after
    check_down(t)
    assert h.result["hands"][0]["label"] == "Three of a kind"


def test_dice_six_changes_nothing():
    t = table("classic", dice=True)
    h = deal(t, ["AsAd", "7c2h"], {"flop": "Kh9c3d", "turn": "5s", "river": "Jd", "dice": "Ah"})
    h.dice_roller = lambda: 6
    check_down(t)
    assert "Ah" not in [repr(c) for cs in h.board_cards().values() for c in cs]
    assert h.result["hands"][0]["label"] == "One pair"


def test_dice_on_big_boards_rolls_per_five_cards():
    v = build_variant("tictactoe", {"private": "2"}).with_dice()
    assert len(v.dice_positions()) == 2 and [len(c) for c in v.dice_positions()] == [5, 4]


# ------------------------------------------------------------ Red River
def test_red_river_deals_again_until_black():
    t = table("redriver")
    # river Kh (red) -> river 2 Qd (red) -> river 3 2s (black) -> showdown
    h = deal(t, ["AsAd", "7c7d"], {"flop": "Ah9c3d", "turn": "5s", "river": "Kh",
                                   "river2": "Qd", "river3": "2s", "river4": "7h"})
    check_down(t)
    b = h.board_cards()
    assert b["river2"] == parse_cards("Qd") and b["river3"] == parse_cards("2s")
    assert b["river4"] == [] and h.rr_stop                 # 7h was never really dealt
    assert h.result["hands"][1]["label"] == "One pair"      # not trips with the phantom 7h
    streets = [x["street"] for x in h.history if x["kind"] == "action"]
    assert "River 3" in streets and "River 4" not in streets


def test_red_river_black_river_ends_normally():
    t = table("redriver")
    h = deal(t, ["AsAd", "7c7d"], {"flop": "Ah9c3d", "turn": "5s", "river": "Ks", "river2": "7h"})
    check_down(t)
    assert h.board_cards()["river2"] == []
    assert stacks(t) == [1010, 990]


# ------------------------------------------------------------ Short Deck / Royal
def test_short_deck_flush_beats_full_house():
    t = table("classic", deck="short")
    assert len(t.settings.variant().deck) == 36
    h = deal(t, ["AhTh", "KsKd"], {"flop": "Kh9h7h", "turn": "7s", "river": "6c"})
    check_down(t)
    assert h.result["hands"][0]["label"] == "Flush"
    assert h.result["hands"][1]["label"] == "Full house"
    assert stacks(t) == [1010, 990]


def test_royal_deck():
    v = TableSettings(variant_id="classic", deck="royal").variant()
    assert len(v.deck) == 20 and {repr(c)[0] for c in v.deck} == set("TJQKA")


def test_deck_choice_works_across_games():
    # Short deck switches poker rows to Short Deck ranking; Hi-Lo has no low without 2-5
    v = TableSettings(variant_id="rows", deck="short").variant()
    assert all(r.kind == "short" for r in v.rows) and len(v.deck) == 36
    with pytest.raises(Exception):
        TableSettings(variant_id="hilo", deck="royal").variant()
    with pytest.raises(Exception):                   # 20 cards can't deal a pyramid
        TableSettings(variant_id="pyramid", deck="royal").variant().validate(2)


# ------------------------------------------------------------ Omaha Hi-Lo
def test_hilo_splits_high_and_low():
    t = table("hilo")
    # P0: high = set of kings; P1: low A-2-3-4-6
    h = deal(t, ["KsKdQcJc", "As2d9h9s"], {"flop": "Kh3c4d", "turn": "6s", "river": "Td"})
    check_down(t)
    labels = {r["row"]: r["label"] for r in h.result["hands"][1]["rows"]}
    assert labels["low"] == "6-4-3-2-A low"
    assert stacks(t) == [1000, 1000]                      # high to P0, low to P1


def test_hilo_no_low_high_takes_all():
    t = table("hilo")
    h = deal(t, ["KsKdQcJc", "As2d9h9s"], {"flop": "KhTc9d", "turn": "Js", "river": "Qd"})
    check_down(t)
    assert stacks(t)[0] + stacks(t)[1] == 2000 and stacks(t)[0] != stacks(t)[1]


# ------------------------------------------------------------ Courchevel / shapes
def test_courchevel_shows_a_flop_card_before_preflop_betting():
    t = table("courchevel")
    h = deal(t, ["AsAdKcKh2c", "7c7d3s4h5h"], {"flop1": "Ah", "flop2": "9c2d", "turn": "5s",
                                                "river": "Jd"})
    assert h.street_name == "Preflop" and h.board_cards()["flop1"] == parse_cards("Ah")
    assert h.actor_seat is not None


def test_iron_cross_and_chowaha_lines():
    ic = build_variant("ironcross", {"private": "4"})
    assert {r.id: r.groups for r in ic.rows} == {"across": ("left", "centre", "right"),
                                                  "down": ("top", "centre", "bottom")}
    ch = build_variant("chowaha", {"private": "2"})
    assert [r.groups for r in ch.rows] == [("f1", "t1", "river"), ("f2", "t1", "river"),
                                          ("f2", "t2", "river"), ("f3", "t2", "river")]
    assert all(r.hole_use == (2,) for r in ch.rows)


# ------------------------------------------------------------ Blackjack Hold'em
def test_blackjack_hits_bust_and_21_half():
    t = table("blackjack", n=3)
    # P0 AsKd = 21 (stands automatically?) no: P0 is a person, stands; P1 hits to bust
    h = deal(t, ["AsKd", "9c8d", "2c3d"], {"flop": "Qh7c4s", "turn": "Jd", "river": "5c"})
    check_down(t, until=lambda h: h.phase_turn is not None)
    check_down(t)
    assert h.phase_turn[0] == "hit"
    order = []
    while h.phase_turn:
        seat = h.phase_turn[1]
        order.append(seat)
        if seat == 1:
            t.phase_action(1, "hit", seq=t.seq)                       # 17 + ? -> deck card
        else:
            t.phase_action(seat, "stand", seq=t.seq)
    check_down(t)
    res = h.result
    assert res["hands"][0]["rows"][1]["label"] == "Blackjack 21"
    assert sum(stacks(t)) == 3000


def test_blackjack_bust_player_is_out():
    t = table("blackjack")
    h = deal(t, ["9c8d", "2c3d"], {"flop": "Qh7c4s", "turn": "Jd", "river": "5c"})
    check_down(t)
    while h.phase_turn:
        seat = h.phase_turn[1]
        t.phase_action(seat, "hit" if seat == 0 else "stand", seq=t.seq)
    if 0 in h.dead:
        check_down(t)
        assert stacks(t)[1] > 1000                         # the bust player can't win
    assert sum(stacks(t)) == 2000


def test_bj_total_counts_aces_soft():
    assert ev.bj_total(parse_cards("AsKd")) == 21
    assert ev.bj_total(parse_cards("AsAd9c")) == 21
    assert ev.bj_total(parse_cards("KsQd5c")) == 25


# ------------------------------------------------------------ Wall Street
def test_wall_street_market_buying_and_pot():
    t = table("wallstreet", {"market": "4"}, n=2)
    v = t.settings.variant()
    h = t.start_hand(force_button=1)
    assert h.phase_turn == ("buy", 0) and len(h.market) == 4
    before = h.stack(0)
    card = h.market[0]
    price = h.price(card)
    t.phase_action(0, "buy", repr(card), seq=t.seq)
    assert h.stack(0) == before - price and card in h.dealt[0] and card in h.up_cards
    assert card not in h.market and len(h.market) == 4    # refilled
    assert h.phase_turn == ("buy", 1)
    while h.phase_turn:
        seat = h.phase_turn[1]
        t.phase_action(seat, "buy", repr(h.market[0]), seq=t.seq)
    assert len(h.bought[0]) == 3 and len(h.bought[1]) == 3
    assert t.total_chips() == 2000
    check_down(t)
    assert sum(stacks(t)) == 2000
    assert len(h.result["hands"][0]["cards"]) == 5


def test_wall_street_prices():
    t = table("wallstreet")
    h = t.start_hand(force_button=1)
    assert h.price(parse_cards("9s")[0]) == 10 and h.price(parse_cards("Ks")[0]) == 20
    assert h.price(parse_cards("As")[0]) == 30


def test_wall_street_fold_in_market():
    t = table("wallstreet", n=3)
    h = t.start_hand(force_button=2)
    t.phase_action(0, "market_fold", seq=t.seq)
    assert 0 in h.dead
    while h.phase_turn:
        t.phase_action(h.phase_turn[1], "buy", repr(h.market[0]), seq=t.seq)
    check_down(t)
    assert all(w["seat"] != 0 for p in h.result["pots"] for w in p["winners"])
    assert sum(stacks(t)) == 3000


# ------------------------------------------------------------ 7-2 bounty
def test_seven_deuce_bounty_paid_by_everyone():
    t = table("classic", n=3, bounty=True)
    deal(t, ["7c2h", "3s4d", "5c6d"], {"flop": "7d7s2c", "turn": "Kd", "river": "Qh"})
    check_down(t)
    bb = BOUNTY_BB * 10
    assert stacks(t)[0] == 1000 + 20 + 2 * bb
    assert sum(stacks(t)) == 3000
    assert t.hand.result["bounty"][0]["seat"] == 0


@pytest.mark.parametrize("vid,opts,add", [
    ("redriver", {}, {}), ("classic", {"private": "4", "rule": "fix2"}, {"deck": "short"}),
    ("hilo", {"private": "5"}, {}), ("courchevel", {}, {}), ("ironcross", {"private": "5"}, {}),
    ("chowaha", {"private": "4"}, {}), ("blackjack", {}, {"dice": True}),
    ("wallstreet", {"market": "5"}, {"bounty": True}), ("classic", {}, {"pineapple": "flop", "deck": "royal"}),
    ("classic", {"private": "5", "rule": "fix2"}, {"pineapple": "every"}),
    ("floors", {}, {"bounty": True}),
])
def test_new_games_soak(vid, opts, add):
    from test_soak import ChaosBot, run
    rng = random.Random(21)
    t = Table(seat_count=4, rng=rng, settings=TableSettings(
        300, 10, 10, vid, tuple(sorted(opts.items())), claim=True, **add))
    bots = {}
    for i in range(4):
        t.sit(i, f"P{i}", is_bot=(i >= 2))
        bots[i] = ChaosBot(rng)
    run(t, bots, 12, rng, humans={0, 1})
