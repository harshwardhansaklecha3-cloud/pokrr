"""Automated hands for every variation: no crashes, only legal actions,
chips conserved, and human declarations accepted/handled."""
import random

import pytest

from bots import BasicBot
from engine import evaluate as ev
from engine.cards import card_str
from engine.table import Table, TableSettings
from engine.variants import PRESETS, get_preset


class ChaosBot:
    """Uniformly random legal actions with random sizes."""

    def __init__(self, rng):
        self.rng = rng

    def decide(self, view, variant=None):
        L = view["legal"]
        options = []
        if L["fold"]:
            options.append(("fold", None))
        if L["check"]:
            options.append(("check", None))
        if L["call"]:
            options.append(("call", None))
        if L["raise_kind"]:
            lo, hi = L["min_to"], L["max_to"]
            options.append((L["raise_kind"], self.rng.choice([lo, hi, self.rng.randint(lo, hi)])))
        return self.rng.choice(options)


def human_declaration(table, seat, rng):
    """What a human might submit: the best choice, or (for 'declare'
    variations) sometimes a deliberately different legal choice."""
    h = table.hand
    v = h.variant
    best = ev.auto_declaration(v, h.dealt[seat], h.board_cards())
    decl = {}
    for r in v.rows:
        if best[r.id] is None:                    # no legal hand here: leave it empty
            decl[r.id] = {"hole": [], "board": []}
            continue
        hand, hole_used, board_used = best[r.id]
        if v.split_hole_cards and v.selection == "auto":
            # give the row its whole allocation: the used cards + leftovers
            decl[r.id] = {"hole": [card_str(c) for c in hole_used], "board": []}
        else:
            decl[r.id] = {"hole": [card_str(c) for c in hole_used],
                          "board": [card_str(c) for c in board_used
                                    if not isinstance(c, ev.RowJoker)]}   # free jokers are automatic
    if v.split_hole_cards and v.selection == "auto":
        # top up each row to exactly hole_alloc with unused cards
        used = {c for d in decl.values() for c in d["hole"]}
        spare = [card_str(c) for c in h.dealt[seat] if card_str(c) not in used]
        for r in v.rows:
            while len(decl[r.id]["hole"]) < r.hole_alloc:
                decl[r.id]["hole"].append(spare.pop())
    return decl


def run(table, bots, hands, rng, humans=()):
    expected = table.chips_added
    for _ in range(hands):
        if not table.can_start_hand()[0]:
            for s in table.seats:
                if s and s.stack == 0:
                    table.rebuy(s.index)
            expected = table.chips_added
        table.start_hand()
        steps = 0
        while table.hand_in_progress:
            h = table.hand
            turn = h.phase_turn
            if turn:                                 # Blackjack hit/stand, Wall Street market
                kind, seat = turn
                assert seat in humans
                if kind == "hit":
                    table.phase_action(seat, rng.choice(["hit", "stand"]), seq=table.seq)
                elif kind == "bid":
                    m = h.auction_min()
                    if rng.random() < 0.5 and m < h.stack(seat):
                        table.phase_action(seat, "bid", str(m), seq=table.seq)
                    else:
                        table.phase_action(seat, "drop", seq=table.seq)
                else:
                    ok = [card_str(c) for c in h.market if h.price(c) < h.stack(seat)]
                    if rng.random() < 0.1:
                        table.phase_action(seat, "market_fold", seq=table.seq)
                    else:
                        table.phase_action(seat, "buy", rng.choice(ok), seq=table.seq)
                assert table.total_chips() == expected
                continue
            if h.pass_awaiting:
                seat = sorted(h.pass_awaiting)[0]
                assert seat in humans
                taken = h.pass_choices.get(seat, []) if h.variant.pass_mode == "discard" else []
                mine = [c for c in h.dealt[seat] if c not in h.up_cards and c not in taken]
                table.pass_card(seat, card_str(rng.choice(mine)), seq=table.seq)
                continue
            if h.awaiting:
                seat = sorted(h.awaiting)[0]
                assert seat in humans
                table.declare(seat, human_declaration(table, seat, rng), seq=table.seq)
                continue
            seat = h.actor_seat
            view = table.view(seat)
            ups = {card_str(c) for c in h.up_cards}
            for s in view["seats"]:          # only own cards, face-up or shown ones
                if not s["empty"] and s["index"] != seat and s["cards"]:
                    assert s["index"] in h.shown or all(c is None or c in ups for c in s["cards"])
            kind, amount = bots[seat].decide(view, h.variant)
            table.act(seat, kind, amount, seq=table.seq)
            assert table.total_chips() == expected
            steps += 1
            assert steps < 500
        assert table.total_chips() == expected
        res = table.hand.result
        assert sum(res["net"].values()) == 0
        assert sum(p["amount"] for p in res["pots"]) == sum(a for a, _ in table.hand.pots_at_showdown)


def combos_for(preset_id, players):
    p = get_preset(preset_id)
    return [c for c in p.combos() if _ok(p, c, players)]


def _ok(p, c, n):
    try:
        p.make(c).validate(n)
        return True
    except Exception:
        return False


@pytest.mark.parametrize("preset_id", list(PRESETS))
def test_chaos_bots_every_variation(preset_id):
    rng = random.Random(hash(preset_id) % 1000)
    players = 4
    for combo in combos_for(preset_id, players):
        t = Table(seat_count=players, rng=rng, settings=TableSettings(
            200, 10, 10, preset_id, tuple(sorted(combo.items()))))
        bots = {}
        for i in range(players):
            t.sit(i, f"C{i}", is_bot=True, stack=rng.choice([30, 120, 200]))
            bots[i] = ChaosBot(rng)
        run(t, bots, 40, rng)


@pytest.mark.parametrize("preset_id", list(PRESETS))
def test_humans_declare_in_every_variation(preset_id):
    """Two 'humans' who must split/pick cards themselves + one chaos bot."""
    rng = random.Random(5)
    for combo in combos_for(preset_id, 3):
        t = Table(seat_count=3, rng=rng, settings=TableSettings(
            300, 10, 10, preset_id, tuple(sorted(combo.items()))))
        bots = {}
        for i in range(3):
            t.sit(i, f"H{i}", is_bot=(i == 2))
            bots[i] = ChaosBot(rng)
        run(t, bots, 15, rng, humans={0, 1})


@pytest.mark.parametrize("seed", range(6))
def test_random_dealer_choices_with_addons(seed):
    """Random families + options + special cards + Anaconda, with two humans
    (who split/pick/pass) and two bots. Chips must balance every step."""
    from engine.table import random_choice
    rng = random.Random(100 + seed)
    for k in range(10):
        sel = random_choice(4, rng)
        t = Table(seat_count=4, rng=rng, settings=TableSettings(300, 10, 10).with_choice(sel))
        bots = {}
        for i in range(4):
            t.sit(i, f"P{i}", is_bot=i >= 2)
            bots[i] = ChaosBot(rng)
        run(t, bots, 3, rng, humans={0, 1})


def test_classic_chaos_tiny_stacks_many_hands():
    rng = random.Random(1)
    t = Table(seat_count=6, settings=TableSettings(200, 5, 10), rng=rng)
    bots = {}
    for i in range(6):
        t.sit(i, f"C{i}", is_bot=True, stack=rng.choice([15, 50, 200, 333]))
        bots[i] = ChaosBot(rng)
    run(t, bots, 400, rng)


@pytest.mark.parametrize("preset_id", ["holdem", "pyramid", "elevator", "two_or_three"])
def test_basic_bots_play_legally(preset_id):
    rng = random.Random(11)
    t = Table(seat_count=4, settings=TableSettings(500, 10, 10, preset_id), rng=rng)
    bots = {}
    for i in range(4):
        t.sit(i, f"B{i}", is_bot=True)
        bots[i] = BasicBot(random.Random(i), samples=8)
    run(t, bots, 6, rng)


def test_bot_equity_sanity():
    from bots.basic import _cards, estimate_equity
    from engine.variants import HOLDEM
    r = random.Random(0)
    aa = estimate_equity(HOLDEM, _cards(["As", "Ah"]), {}, 1, [], 600, r, time_budget=30)
    junk = estimate_equity(HOLDEM, _cards(["7d", "2c"]), {}, 1, [], 600, r, time_budget=30)
    assert 0.78 < aa < 0.9 and 0.25 < junk < 0.42
    nuts = estimate_equity(HOLDEM, _cards(["As", "Ks"]),
                           {"flop": _cards(["Qs", "Js", "Ts"])}, 3, [], 100, r)
    assert nuts == 1.0
