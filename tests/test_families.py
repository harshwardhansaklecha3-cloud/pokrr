"""Game families, Teen Patti / Poker Patti, Personal board, Anaconda passing
and community-card jokers."""
import json

import pytest

from engine import evaluate as ev
from engine.cards import STANDARD_52, Shoe, parse_cards
from engine.hand import IllegalAction
from engine.table import Table, TableSettings, preview_choice
from engine.variants import build_variant


def check_down(t):
    while t.hand_in_progress and t.hand.actor_seat is not None:
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)


def deal_order_shoe(variant, players: list[str], later_hole: list[list[str]] = (),
                    board: dict | None = None) -> Shoe:
    """Stacked shoe that also handles cards dealt to players on later streets
    (e.g. Personal board): later_hole[stage_k][player] = card."""
    holes = [parse_cards(p) for p in players]
    board = {g: parse_cards(c) for g, c in (board or {}).items()}
    used = [c for h in holes for c in h] + [c for cs in board.values() for c in cs] \
        + [c for st in later_hole for c in parse_cards("".join(st))]
    filler = iter([c for c in STANDARD_52 if c not in set(used)])
    order = []
    n0 = variant.stages[0].hole_cards
    for k in range(n0):
        for h in holes:
            order.append(h[k])
    later = iter(later_hole)
    for stage in variant.stages[1:]:
        if stage.burn:
            order.append(next(filler))
        if stage.hole_cards:
            cards = parse_cards("".join(next(later)))
            order += cards
        for gid in stage.reveal:
            want = list(board.get(gid, []))
            for _ in range(variant.group(gid).size):
                order.append(want.pop(0) if want else next(filler))
    order += list(filler)
    return Shoe.stacked(order)


def table(settings, n, bots=()):
    t = Table(seat_count=n, settings=settings)
    for i in range(n):
        t.sit(i, f"P{i}", is_bot=i in bots)
    return t


# ------------------------------------------------------------ Teen Patti
@pytest.mark.parametrize("better,worse", [
    ("7s7h7d", "AsKsQs"),     # trail > pure sequence
    ("AsKsQs", "As2s3s"),     # A-K-Q is the top pure sequence, then A-2-3
    ("As2s3s", "KsQsJs"),
    ("4h5h6h", "AsKdQc"),     # pure sequence > sequence
    ("AsKdQc", "As2d3c"),     # sequences: A-K-Q > A-2-3
    ("2s3d4c", "AhKh9h"),     # sequence > color
    ("AhKh9h", "AsAd2c"),     # color > pair
    ("AsAd2c", "KsKdAc"),     # pair of aces > pair of kings
    ("KsKdAc", "AsQd9c"),     # pair > high card
])
def test_teen_patti_ranking(better, worse):
    assert ev.score3(parse_cards(better)) > ev.score3(parse_cards(worse))


def test_teen_patti_wild_card_counts_as_printed():
    """Owner 2026-11-10: wilds only help the poker hand; in Teen Patti a wild
    plays as its printed card, and a joker can't be used."""
    w = ev.Wild(parse_cards("5c")[0])
    hand = ev.score3(tuple(parse_cards("KhKs")) + (w,))
    assert hand.tp_label == "Pair"
    j = ev.Wild(ev.JOKER_BY_CODE["X1"])
    assert ev.score3(tuple(parse_cards("KhKs")) + (j,)) < ev.score3(parse_cards("2c3d5h"))


def test_low_hand_wild_counts_as_printed():
    w = ev.Wild(parse_cards("Kc")[0])
    assert ev.score_low(tuple(parse_cards("As2d3h4c")) + (w,)) is None      # K: no low
    w = ev.Wild(parse_cards("5c")[0])
    assert ev.score_low(tuple(parse_cards("As2d3h4c")) + (w,)) is not None  # the wheel


def test_poker_patti_pot_split_between_poker_and_teen_patti():
    s = TableSettings(1000, 10, 10, "poker_patti", (("style", "texas"),))
    v = s.variant()
    t = table(s, 2)
    shoe = deal_order_shoe(v, ["AhAd7s8s9s", "2c3c4d4h4s"],
                           board={"flop": "AsKd2h", "turn": "Qc", "river": "Jd"})
    t.start_hand(shoe, force_button=1)
    check_down(t)
    assert t.hand.awaiting == {0, 1}
    with pytest.raises(IllegalAction, match="exactly 3"):
        t.declare(0, {"poker": {"hole": ["Ah", "Ad"]}, "patti": {"hole": ["7s", "8s"]}}, seq=t.seq)
    # P0: AA to poker (trip aces), 7-8-9 spades to Teen Patti (pure sequence)
    t.declare(0, {"poker": {"hole": ["Ah", "Ad"]}, "patti": {"hole": ["7s", "8s", "9s"]}}, seq=t.seq)
    # P1: 2c3c to poker, 444 to Teen Patti (trail beats pure sequence)
    t.declare(1, {"poker": {"hole": ["2c", "3c"]}, "patti": {"hole": ["4d", "4h", "4s"]}}, seq=t.seq)
    res = t.hand.result
    won = {p["row"]: p["winners"][0]["seat"] for p in res["pots"]}
    assert won == {"poker": 0, "patti": 1}
    labels = {r["row"]: r["label"] for r in res["hands"][1]["rows"]}
    assert labels["patti"] == "Trail"
    assert [x.stack for x in t.seats] == [1000, 1000]


# ------------------------------------------------------------ Personal board
def test_personal_board_face_up_cards_visible_but_private_cards_hidden():
    s = TableSettings(1000, 10, 10, "personal", (("private", "2"),))
    v = s.variant()
    t = table(s, 2)
    shoe = deal_order_shoe(v, ["AhKh", "2c3d"], later_hole=[["Qh", "9s"], ["Jh", "8s"]],
                           board={"flop": "Th4c5d"})
    t.start_hand(shoe, force_button=1)
    check_down(t)
    res = t.hand.result
    assert res["hands"][0]["label"] == "Royal flush"     # A K Q J T of hearts
    # mid-hand visibility (replay to the turn)
    t2 = table(s, 2)
    t2.start_hand(deal_order_shoe(v, ["AhKh", "2c3d"], later_hole=[["Qh", "9s"], ["Jh", "8s"]],
                                  board={"flop": "Th4c5d"}), force_button=1)
    for _ in range(4):        # preflop + flop betting
        L = t2.hand.legal_actions(t2.hand.actor_seat)
        t2.act(t2.hand.actor_seat, "check" if L.check else "call", seq=t2.seq)
    view = t2.view(1)
    p0 = view["seats"][0]["cards"]
    assert p0 is not None and "Qh" in p0                     # P0's face-up turn card
    # (the "nuts" hint is built from community cards only; its EXAMPLE royal
    # flush can coincidentally name these cards, so it's left out of this check)
    blob = json.dumps({k: x for k, x in view.items() if k != "nuts"})
    assert '"Ah"' not in blob and '"Kh"' not in blob           # P0's private cards stay hidden


# ------------------------------------------------------------ Anaconda
def test_anaconda_pass_moves_card_left_and_stays_private():
    s = TableSettings(1000, 10, 10, "classic", (("private", "2"), ("rule", "any")),
                      anaconda="flop")
    v = s.variant()
    t = table(s, 3, bots=(2,))
    t.start_hand(deal_order_shoe(v, ["AhAd", "KhKd", "QhQd"],
                                 board={"flop": "2c3c4c", "turn": "9s", "river": "Ts"}),
                 force_button=2)
    for _ in range(6):        # preflop (3 actions) + flop (3 checks)
        L = t.hand.legal_actions(t.hand.actor_seat)
        t.act(t.hand.actor_seat, "check" if L.check else "call", seq=t.seq)
    h = t.hand
    assert h.pass_awaiting == {0, 1}                     # humans must pass; bot already chose
    view0 = t.view(0)
    assert view0["pass"] and set(view0["pass"]["cards"]) == {"Ah", "Ad"}
    with pytest.raises(IllegalAction):
        t.pass_card(0, "Kh", seq=t.seq)                   # not your card
    t.pass_card(0, "Ah", seq=t.seq)
    assert h.pass_awaiting == {1}
    t.pass_card(1, "Kd", seq=t.seq)
    # P0 -> P1 -> P2 -> P0 (left = next seat clockwise)
    assert sorted(t.view(0)["seats"][0]["cards"]) == sorted(["Ad", h.hole_cards(0)[-1]])
    assert "Ah" in t.view(1)["seats"][1]["cards"]
    assert "Kd" in t.view(2)["seats"][2]["cards"] or "Kd" in h.hole_cards(2)
    # nobody else sees the passed cards
    assert '"Ah"' not in json.dumps(t.view(2)) and '"Kd"' not in json.dumps(t.view(0))
    check_down(t)
    assert not t.hand_in_progress
    assert sum(x.stack for x in t.seats) == 3000
    # each player's shown hand is what they held AFTER the pass
    assert "Ah" in t.hand.shown[1]


# ------------------------------------------------------------ community jokers
def test_joker_scope_all_makes_board_cards_wild():
    v = build_variant("classic").with_special("joker", "River", "all")
    board = {"flop": parse_cards("2c7d9h"), "turn": parse_cards("Ks"), "river": parse_cards("4h"),
             "special": parse_cards("7s")}
    res = ev.auto_declaration(v, parse_cards("KhKd"), board)
    assert v.explain(res["main"][0]).label == "Four of a kind"   # KK + K + wild 7d as K
    v2 = build_variant("classic").with_special("joker", "River", "private")
    res2 = ev.auto_declaration(v2, parse_cards("KhKd"), board)
    assert v2.explain(res2["main"][0]).label == "Three of a kind"


# ------------------------------------------------------------ families
def test_family_names_and_minimums():
    assert build_variant("classic", {"private": "2", "rule": "any"}).name == "Texas Hold'em"
    assert build_variant("classic", {"private": "4", "rule": "fix2"}).name == "Omaha"
    ok = preview_choice(TableSettings(variant_id="rows", variant_options=(
        ("layout", "3or3or2"), ("pot", "classic"), ("private", "3"), ("rule", "classic"))), 4)
    assert ok["ok"]                                       # 3 private is the minimum
    bad = preview_choice(TableSettings(variant_id="classic", variant_options=(
        ("private", "2"), ("rule", "fix3"))), 4)
    assert not bad["ok"] and bad["reason"]
