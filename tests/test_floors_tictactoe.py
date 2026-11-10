"""Elevator floors, Tic-tac-toe, claiming your hand, and the fast wild-card solver."""
import itertools
import random

import pytest

from engine import evaluate as ev
from engine.cards import STANDARD_52, parse_cards
from engine.table import Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant


# ------------------------------------------------------------ wild solver
def brute(fixed, w):
    rest = [c for c in STANDARD_52 if c not in fixed]
    return max(ev._score_key(frozenset(fixed) | frozenset(sub))
               for sub in itertools.combinations(rest, w))


@pytest.mark.parametrize("w", [1, 2, 3])
def test_wild_solver_matches_brute_force(w):
    rng = random.Random(w)
    for _ in range(250 if w < 3 else 60):
        fixed = frozenset(rng.sample(STANDARD_52, 5 - w))
        assert ev._best_with_wilds(fixed, w) == brute(fixed, w), fixed


def test_wild_solver_tricky_cases():
    for text, w in [("KhKd5c5s", 1), ("AsKsQsJs", 1), ("9h8d", 3), ("2c2d2h", 2),
                    ("As2s3s4d", 1), ("AhAd", 3), ("7c7d", 3), ("5h6h", 3), ("Td9d8d7d", 1)]:
        fixed = frozenset(parse_cards(text))
        assert ev._best_with_wilds(fixed, w) == brute(fixed, w), text


# ------------------------------------------------------------ Elevator floors
# Owner 2026-11-10: 6 private cards, split into 3 pairs (one per floor), a
# claim on each floor, pot in thirds. No options.
def floors():
    return build_variant("floors", {})


def test_floors_layout_and_jokers():
    v = floors()
    assert [g.size for g in v.board_groups[:3]] == [1, 2, 3]
    assert [r.jokers for r in v.rows] == [2, 1, 0]
    assert all(r.hole_use == (2,) and r.hole_alloc == 2 for r in v.rows)
    assert v.hole_card_count == 6 and v.scoring == "split" and v.portions == 3
    assert v.rows[0].groups == ("f1", "turn", "river")
    v.validate(6)


BOARD = {"f1": "2c", "f2": "Kd3h", "f3": "4s5s6d", "turn": "7h", "river": "9s"}


def test_floor_one_two_jokers_make_quads():
    v = floors()
    b = {k: parse_cards(x) for k, x in BOARD.items()}
    res = ev.auto_declaration(v, parse_cards("AsAdQcQh8c8d"), b)
    hands = {r: v.explain(res[r][0]).label for r in ("f1", "f2", "f3")}
    assert "Four of a kind" in hands.values()                         # a pair + 2 jokers
    pairs = [set(map(str, res[r][1])) for r in ("f1", "f2", "f3")]
    assert all(len(p) == 2 for p in pairs) and len(set().union(*pairs)) == 6   # 3 pairs, no reuse


def test_floors_claim_each_floor_pot_in_thirds():
    v = floors().with_claims()
    t = Table(seat_count=2, settings=TableSettings(1000, 10, 10, "floors", (), claim=True))
    t.sit(0, "Me"); t.sit(1, "Bot", is_bot=True)
    t.start_hand(stacked_variant(v, ["AsAdQcQh8c8d", "JhTh3c3d4c4d"], BOARD), force_button=1)
    while t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)
    assert t.hand.awaiting == {0}
    from engine.hand import IllegalAction
    with pytest.raises(IllegalAction):                  # the same card on two floors
        t.declare(0, {"f1": {"hole": ["As", "Ad"], "board": ["9s"]},
                      "f2": {"hole": ["As", "Qh"], "board": ["Kd", "7h", "9s"]},
                      "f3": {"hole": ["8c", "8d"], "board": ["4s", "5s", "6d"]}}, seq=t.seq)
    t.declare(0, {"f1": {"hole": ["As", "Ad"], "board": ["9s"]},
                  "f2": {"hole": ["Qc", "Qh"], "board": ["Kd", "9s"]},
                  "f3": {"hole": ["8c", "8d"], "board": ["4s", "5s", "6d"]}}, seq=t.seq)
    res = t.hand.result
    assert len([p for p in res["pots"] if p["row"]]) == 3            # a showdown per floor
    me = res["hands"][0]
    assert len(me["rows"]) == 3
    assert sum(1 for p in me["rows"][0]["played"] if p["joker"] == "🃏") == 2


# ------------------------------------------------------------ Tic-tac-toe
def test_tictactoe_grid_order_and_lines():
    v = build_variant("tictactoe", {"private": "4"})
    assert v.stages[1].reveal == ("c00", "c02", "c20", "c22")          # corners
    assert v.stages[2].reveal == ("c01", "c10", "c12", "c21")          # edges
    assert v.stages[3].reveal == ("c11",)                              # centre
    assert len(v.rows) == 8 and all(r.hole_use == (2,) for r in v.rows)
    assert {g.id for g in v.board_groups} == {f"c{r}{c}" for r in range(3) for c in range(3)}


def test_tictactoe_best_line_wins_and_lines_never_mix():
    # diagonal c00-c11-c22 = As Ks Qs; P0 holds Js Ts -> royal flush on the diagonal
    board = {"c00": "As", "c02": "2d", "c20": "3c", "c22": "Qs",
             "c01": "4h", "c10": "5h", "c12": "8c", "c21": "9d", "c11": "Ks"}
    v = build_variant("tictactoe", {"private": "2"})
    b = {k: parse_cards(x) for k, x in board.items()}
    res = ev.auto_declaration(v, parse_cards("JsTs"), b)
    assert v.explain(res["diag1"][0]).label == "Royal flush"
    assert v.explain(res["row1"][0]).label != "Royal flush"            # row 1 has As but not Ks Qs
    # a claim with cards from two lines is refused
    with pytest.raises(ev.DeclarationError):
        ev.apply_declaration(v.with_claims(), parse_cards("JsTs"), b,
                             {"row1": {"hole": ["Js", "Ts"], "board": ["As", "Ks", "Qs"]}})


def test_one_row_claim_counts_only_that_row():
    v = build_variant("tictactoe", {"private": "2"}).with_claims()
    board = {"c00": "As", "c02": "2d", "c20": "3c", "c22": "Qs",
             "c01": "4h", "c10": "5h", "c12": "8c", "c21": "9d", "c11": "Ks"}
    b = {k: parse_cards(x) for k, x in board.items()}
    # claim the weak top row although the diagonal is a royal flush: it counts as claimed
    out = ev.apply_declaration(v, parse_cards("JsTs"), b,
                               {"row1": {"hole": ["Js", "Ts"], "board": ["As", "2d", "4h"]}})
    assert out["diag1"] is None and v.explain(out["row1"][0]).label == "High card"
    with pytest.raises(ev.DeclarationError, match="claim a hand in at least one row"):
        ev.apply_declaration(v, parse_cards("JsTs"), b, {})


def test_claims_in_poker_patti_teen_patti_row():
    v = build_variant("poker_patti", {"style": "texas"}).with_claims()
    b = {"flop": parse_cards("2c7d9h"), "turn": parse_cards("Kc"), "river": parse_cards("4s")}
    hole = parse_cards("AsAhQdQcQs")
    out = ev.apply_declaration(v, hole, b, {
        "poker": {"hole": ["As", "Ah"], "board": ["Kc", "9h", "7d"]},
        "patti": {"hole": ["Qd", "Qc", "Qs"]}})
    assert out["patti"][0].tp_label == "Trail"
    assert v.explain(out["poker"][0]).label == "One pair"


# ------------------------------------------------------------ nuts hints
def brute_top_two(v, board):
    """Every possible 2-card holding from the unseen cards (2-card games)."""
    seen = {c for cards in board.values() for c in cards}
    rest = [c for c in STANDARD_52 if c not in seen]
    vals = set()
    for hole in itertools.combinations(rest, 2):
        res = ev.auto_declaration(v, list(hole), board)
        vals.add(max(ev.portion_hands(v, res)))
    top = sorted(vals, reverse=True)[:2]
    return [v.explain(h).label for h in top], top


@pytest.mark.parametrize("vid,opts,deal", [
    ("classic", {"private": "2", "rule": "any"}, {"flop": "Ks8d3c", "turn": "2h", "river": "Jc"}),
    ("classic", {"private": "2", "rule": "any"}, {"flop": "9h8h7d", "turn": "", "river": ""}),
    ("tictactoe", {"private": "2"}, {"c00": "As", "c02": "2d", "c20": "3c", "c22": "Qs",
                                     "c01": "Ks", "c10": "5h", "c12": "8c", "c21": "9d", "c11": ""}),
])
def test_nuts_match_brute_force(vid, opts, deal):
    from engine.nuts import top_two
    v = build_variant(vid, opts)
    board = {g.id: parse_cards(deal.get(g.id, "")) for g in v.board_groups}
    got = top_two(v, board)
    want_labels, want = brute_top_two(v, board)
    assert [x["label"] for x in got] == want_labels
    for x, h in zip(got, want):                          # same exact value, not just category
        assert ev._score_key(frozenset(parse_cards("".join(x["cards"])))) == h


def test_nuts_in_view_use_only_public_cards():
    t = Table(seat_count=2, settings=TableSettings(1000, 10, 10, "classic"))
    t.sit(0, "A"); t.sit(1, "B")
    from helpers import stacked_holdem
    t.start_hand(stacked_holdem(["AsAd", "7c2h"], "Ks8d3c2dJc"), force_button=1)
    assert t.view(0)["nuts"] == []                         # nothing on the board yet
    while t.hand.street_name == "Preflop":
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)
    n0, n1 = t.view(0)["nuts"], t.view(1)["nuts"]
    assert n0 == n1 and n0[0]["label"] == "Three of a kind"   # a set of kings
    assert set(n0[0]["cards"]) >= {"Ks"}


@pytest.mark.parametrize("vid,opts", [("floors", {}),
                                      ("tictactoe", {"private": "3"})])
def test_new_games_soak_with_claims(vid, opts):
    from test_soak import ChaosBot, run
    rng = random.Random(11)
    t = Table(seat_count=4, rng=rng, settings=TableSettings(
        400, 10, 10, vid, tuple(sorted(opts.items())), claim=True))
    bots = {}
    for i in range(4):
        t.sit(i, f"P{i}", is_bot=(i != 0))
        bots[i] = ChaosBot(rng)
    run(t, bots, 10, rng, humans={0})
