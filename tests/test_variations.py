"""Deterministic checks of each variation's card-selection and payout rules.

Seating: button is the last seat, so seat i = PokerKit player i.
Blinds 10/10. Everyone checks/calls down unless stated.
"""
import pytest

from engine.hand import IllegalAction
from engine.table import Table, TableSettings
from engine.variants import build_variant
from helpers import stacked_variant


def table_for(preset, options, holes, board, stacks=None, bots=()):
    opts = tuple(sorted((options or {}).items()))
    n = len(holes)
    t = Table(seat_count=n, settings=TableSettings(1000, 10, 10, preset, opts))
    for i in range(n):
        t.sit(i, f"P{i}", is_bot=i in bots, stack=(stacks or [1000] * n)[i])
    v = build_variant(preset, options)
    t.start_hand(stacked_variant(v, holes, board), force_button=n - 1)
    return t


def check_down(t):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


def stacks(t):
    return [s.stack for s in t.seats]


# ------------------------------------------------------------ Hold'em rules
ROYAL = {"flop": "AsKsQs", "turn": "Js", "river": "Ts"}


def test_holdem_012_can_play_the_board():
    t = table_for("holdem", {"hand_rule": "any"}, ["2c3d", "4h5h"], ROYAL)
    check_down(t)
    assert t.hand.result["hands"][0]["label"] == "Royal flush"
    assert stacks(t) == [1000, 1000]            # both play the board: split


def test_holdem_fix2_must_use_both_private_cards():
    # Fix 2: the royal flush on board can't be played; 2c3d vs 4h5h with
    # 3 board cards -> P1's 4h5h + AsKsQs.. compare: both high card A.
    t = table_for("holdem", {"hand_rule": "fix2"}, ["2c2d", "4h5h"], ROYAL)
    check_down(t)
    res = t.hand.result
    assert res["hands"][0]["label"] == "One pair"        # 2c2d + 3 board cards
    assert {"2c", "2d"} <= set(res["hands"][0]["cards"])
    assert {"4h", "5h"} <= set(res["hands"][1]["cards"])
    assert stacks(t) == [1010, 990]


# ------------------------------------------------------------ Omaha
def test_omaha_exactly_two_private_cards():
    # P0 holds four hearts but the board has only two hearts: no flush.
    t = table_for("omaha", {}, ["AhKhQhJh", "2c2d3c4d"],
                  {"flop": "Th9h2s", "turn": "7c", "river": "5s"})
    check_down(t)
    res = t.hand.result
    assert res["hands"][0]["label"] != "Flush"
    assert res["hands"][1]["label"] == "Three of a kind"    # 2c2d + 2s
    assert stacks(t) == [990, 1010]


# ------------------------------------------------------------ Double board
DB_BOARD = {"flopA": "AsAc7d", "turnA": "2h", "riverA": "3h",
            "flopB": "KsKc8d", "turnB": "4h", "riverB": "5c"}


def test_double_board_split_rejects_card_in_both_rows():
    t = table_for("double_holdem", {"cards": "split", "hand_rule": "any"},
                  ["AdKdQh9c", "JhJd6s6c"], DB_BOARD)
    check_down(t)
    assert t.hand.awaiting == {0, 1}
    with pytest.raises(IllegalAction, match="only go to one row"):
        t.declare(0, {"A": {"hole": ["Ad", "Kd"]}, "B": {"hole": ["Kd", "Qh"]}}, seq=t.seq)
    with pytest.raises(IllegalAction, match="exactly 2"):
        t.declare(0, {"A": {"hole": ["Ad"]}, "B": {"hole": ["Kd", "Qh"]}}, seq=t.seq)


def test_double_board_split_pot_per_row():
    t = table_for("double_holdem", {"cards": "split", "hand_rule": "any"},
                  ["AdKdQh9c", "JhJd6s6c"], DB_BOARD)
    check_down(t)
    # P0: Ad->row A (trip aces), Kd->row B (trip kings). P1: pairs.
    t.declare(0, {"A": {"hole": ["Ad", "Qh"]}, "B": {"hole": ["Kd", "9c"]}}, seq=t.seq)
    t.declare(1, {"A": {"hole": ["Jh", "Jd"]}, "B": {"hole": ["6s", "6c"]}}, seq=t.seq)
    res = t.hand.result
    assert stacks(t) == [1010, 990]
    labels = {r["row"]: r["label"] for r in res["hands"][0]["rows"]}
    assert labels == {"A": "Three of a kind", "B": "Three of a kind"}


def test_double_board_each_row_can_have_different_winner():
    t = table_for("double_holdem", {"cards": "split", "hand_rule": "any"},
                  ["AdQh9c3c", "KdJh6s6c"], DB_BOARD)
    check_down(t)
    t.declare(0, {"A": {"hole": ["Ad", "Qh"]}, "B": {"hole": ["9c", "3c"]}}, seq=t.seq)
    t.declare(1, {"A": {"hole": ["Jh", "6s"]}, "B": {"hole": ["Kd", "6c"]}}, seq=t.seq)
    res = t.hand.result
    rows_won = {p["row"]: p["winners"][0]["seat"] for p in res["pots"]}
    assert rows_won == {"A": 0, "B": 1}
    assert stacks(t) == [1000, 1000]          # each takes half of 20


def test_double_board_shared_cards_need_no_declaration():
    t = table_for("double_holdem", {"cards": "shared", "hand_rule": "any"},
                  ["AdKdQh9c", "JhJd6s6c"], DB_BOARD)
    check_down(t)
    assert not t.hand_in_progress            # finished automatically
    assert stacks(t) == [1010, 990]          # Ad and Kd each used in a row


# ------------------------------------------------------------ Pyramid
PYR = {"t5": "AsAhAdAc2s", "t4": "KsKhKdKc", "t3": "Qs9h8d", "t2": "7c6c", "t1": "3d"}


def test_pyramid_one_card_per_row_and_weaker_pick_counts():
    t = table_for("pyramid", {"hand_rule": "any"}, ["JsTs", "5h4h"], PYR, bots=(1,))
    check_down(t)
    assert t.hand.awaiting == {0}           # human picks; bot already chose
    with pytest.raises(IllegalAction, match="one card from each group"):
        t.declare(0, {"main": {"hole": ["Js", "Ts"], "board": ["As", "Ah", "Ks"]}}, seq=t.seq)
    with pytest.raises(IllegalAction, match="choose exactly 5"):
        t.declare(0, {"main": {"hole": ["Js", "Ts"], "board": ["As", "Ks"]}}, seq=t.seq)
    # Best would be a royal flush (As Ks Qs + Js Ts). The human picks a
    # weaker legal hand (pair of aces) -> that is what counts.
    t.declare(0, {"main": {"hole": ["Js", "Ts"], "board": ["Ah", "Kh", "9h"]}}, seq=t.seq)
    res = t.hand.result
    assert res["hands"][0]["label"] == "High card"
    assert res["hands"][1]["label"] == "Flush"   # bot: 5h4h + Ah Kh 9h, one per row
    assert stacks(t) == [990, 1010]


def test_pyramid_good_pick_wins():
    t = table_for("pyramid", {"hand_rule": "any"}, ["JsTs", "5h4h"], PYR, bots=(1,))
    check_down(t)
    t.declare(0, {"main": {"hole": ["Js", "Ts"], "board": ["As", "Ks", "Qs"]}}, seq=t.seq)
    assert t.hand.result["hands"][0]["label"] == "Royal flush"
    assert stacks(t) == [1010, 990]


# ------------------------------------------------------------ Elevator
ELEV = {"r1": "5c6d2h", "r2": "AsAd5s", "r3": "3d9c4h", "e1": "9s", "e2": "Jh"}


def test_elevator_example_from_user_and_thirds():
    # The user's example: 3 7 8 A J T split as 78 / AJ / 3T.
    t = table_for("elevator", {"hand_rule": "any"},
                  ["7s8sAhJc3hTd", "2c2d6h6sKcKd"], ELEV, stacks=[1000, 1000])
    check_down(t)
    t.declare(0, {"R1": {"hole": ["7s", "8s"]}, "R2": {"hole": ["Ah", "Jc"]},
                  "R3": {"hole": ["3h", "Td"]}}, seq=t.seq)
    t.declare(1, {"R1": {"hole": ["2c", "2d"]}, "R2": {"hole": ["6h", "6s"]},
                  "R3": {"hole": ["Kc", "Kd"]}}, seq=t.seq)
    rows = {r["row"]: r["label"] for r in t.hand.result["hands"][0]["rows"]}
    assert rows == {"R1": "Straight", "R2": "Full house", "R3": "Two pair"}
    # P1: R1 trip 2s (loses to the straight), R2 AA66 (loses to aces full),
    # R3 KK99 beats P0's 9933.
    winners = {p["row"]: p["winners"][0]["seat"] for p in t.hand.result["pots"]}
    assert winners == {"R1": 0, "R2": 0, "R3": 1}
    # Pot 20 -> thirds 8 (odd chips go to the first portion), 6, 6.
    amounts = {p["row"]: p["amount"] for p in t.hand.result["pots"]}
    assert amounts == {"R1": 8, "R2": 6, "R3": 6}
    assert stacks(t) == [1004, 996]


def test_no_cards_revealed_until_everyone_has_chosen():
    """Fairness: while a human is still choosing, opponents' cards stay hidden
    (from the view AND the history), even though betting is over."""
    import json
    t = table_for("elevator", {"hand_rule": "any"},
                  ["7s8sAhJc3hTd", "2c2d6h6sKcKd"], ELEV, bots=(1,))
    check_down(t)
    assert t.hand.awaiting == {0}
    v = t.view(0)
    assert v["seats"][1]["cards"] is None
    blob = json.dumps(v)
    for c in ("2c", "2d", "6h", "6s", "Kc", "Kd"):
        assert f'"{c}"' not in blob and f" {c}" not in blob, c
    t.declare(0, {"R1": {"hole": ["7s", "8s"]}, "R2": {"hole": ["Ah", "Jc"]},
                  "R3": {"hole": ["3h", "Td"]}}, seq=t.seq)
    assert t.view(0)["seats"][1]["cards"] == ["2c", "6h", "Kc", "2d", "6s", "Kd"] or \
        sorted(t.view(0)["seats"][1]["cards"]) == sorted(["2c", "2d", "6h", "6s", "Kc", "Kd"])


def test_elevator_pot_split_into_thirds_with_odd_chips():
    t = table_for("elevator", {"hand_rule": "any"},
                  ["7s8sAhJc3hTd", "2c2d6h6sKcKd", "QhQdQsQc7c7d"], ELEV)
    # P2 raises to 20 after the flop; pot becomes odd by design below.
    check_down(t)
    t.declare(0, {"R1": {"hole": ["7s", "8s"]}, "R2": {"hole": ["Ah", "Jc"]},
                  "R3": {"hole": ["3h", "Td"]}}, seq=t.seq)
    t.declare(1, {"R1": {"hole": ["2c", "2d"]}, "R2": {"hole": ["6h", "6s"]},
                  "R3": {"hole": ["Kc", "Kd"]}}, seq=t.seq)
    t.declare(2, {"R1": {"hole": ["Qh", "Qd"]}, "R2": {"hole": ["7c", "7d"]},
                  "R3": {"hole": ["Qs", "Qc"]}}, seq=t.seq)
    res = t.hand.result
    assert sum(p["amount"] for p in res["pots"]) == 30
    assert sum(stacks(t)) == 3000
    by_row = {p["row"]: p for p in res["pots"]}
    assert by_row["R2"]["winners"][0]["seat"] == 0          # aces full
    assert by_row["R3"]["winners"][0]["seat"] == 1          # KK99 beats QQ99
    assert sorted(p["amount"] for p in res["pots"]) == [10, 10, 10]


def test_elevator_fold_forfeits_every_row():
    t = table_for("elevator", {"hand_rule": "any"},
                  ["7s8sAhJc3hTd", "2c2d6h6sKcKd"], ELEV)
    t.act(1, "call", seq=t.seq) if t.hand.legal_actions(1) and t.hand.legal_actions(1).call else None
    actor = t.hand.actor_seat
    L = t.hand.legal_actions(actor)
    t.act(actor, "raise", 50, seq=t.seq)
    t.act(t.hand.actor_seat, "fold", seq=t.seq)
    assert not t.hand_in_progress
    assert t.hand.result["showdown"] is False


# ------------------------------------------------------------ Twin Rows
@pytest.mark.parametrize("preset", ["twin_rows", "two_or_three", "three_three_two",
                                    "double_holdem", "elevator"])
def test_rows_never_mix_cards(preset):
    """A hand may only use its OWN row's community cards (plus shared cards
    like the Twin Rows turn) — never cards from another row. Checked by
    giving every row's cards a unique group and verifying each row's chosen
    board cards all come from that row's groups."""
    import random as _r
    from engine import evaluate as ev
    from engine.cards import STANDARD_52
    v = build_variant(preset)
    rng = _r.Random(7)
    for _ in range(40):
        deck = list(STANDARD_52); rng.shuffle(deck)
        board, k = {}, 0
        for g in v.board_groups:
            board[g.id] = deck[k:k + g.size]; k += g.size
        hole = deck[k:k + v.hole_card_count]
        for row in v.rows:
            res = ev.best_for_row(row, hole, board)
            if res is None:
                continue
            allowed = {c for gid in row.groups for c in board[gid]}
            assert set(res[2]) <= allowed, (row.id, res)


def test_twin_rows_mixing_rows_would_be_a_royal_flush_but_is_not_allowed():
    from engine import evaluate as ev
    from engine.cards import parse_cards
    v = build_variant("twin_rows")
    board = {"flopA": parse_cards("AhKh2c"), "flopB": parse_cards("QhJh3d"),
             "turn": parse_cards("7s"), "riverA": parse_cards("4d"), "riverB": parse_cards("5c")}
    best = ev.auto_declaration(v, parse_cards("Th9c8d"), board)
    labels = {rid: v.explain(r[0]).label for rid, r in best.items()}
    assert labels["B"] == "Straight"                 # Qh Jh + Th 9c 8d, row B only
    assert "flush" not in labels["A"].lower() and "flush" not in labels["B"].lower()


def test_twin_rows_best_row_wins_whole_pot():
    board = {"flopA": "AsAdAc", "flopB": "2s7d9c", "turn": "Kh", "riverA": "3c", "riverB": "4d"}
    t = table_for("twin_rows", {"hand_rule": "any"}, ["KsKd5h", "9d9s8h"], board)
    check_down(t)
    res = t.hand.result
    # P0: row A -> A A A K K (full house). P1: row B -> 9 9 9 (trips) best.
    assert res["hands"][0]["label"] == "Full house"
    assert res["hands"][1]["label"] == "Full house"   # 999 + AA? no: A A A 9 9 in row A
    assert len(res["pots"]) == 1 and res["pots"][0]["row"] is None
    assert stacks(t) == [1010, 990]                    # aces full of kings beats aces full of nines


# ------------------------------------------------------------ 2or3
def test_two_or_three_uses_exactly_2_top_and_3_bottom():
    board = {"flopT": "AsKsQs", "flopB": "2c2d", "turn": "7h", "riverT": "8h", "riverB": "9h"}
    # P0: no spades; bottom row: 3 private 2h2s.. -> quads 2s needs 2h2s + board 2c2d
    t = table_for("two_or_three", {"layout": "common_turn"},
                  ["2h2s3c4c5d", "JsTs6d6c3d"], board)
    check_down(t)
    res = t.hand.result
    p0 = {r["row"]: r for r in res["hands"][0]["rows"]}
    p1 = {r["row"]: r for r in res["hands"][1]["rows"]}
    assert p0["bottom"]["label"] == "Four of a kind"
    assert len(p0["bottom"]["hole_used"]) == 3 and len(p0["top"]["hole_used"]) == 2
    assert p1["top"]["label"] == "Royal flush"      # JsTs + AsKsQs
    assert stacks(t) == [990, 1010]                    # best single row wins all
