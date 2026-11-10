"""A transparent baseline bot that works for every POKRR variation.

It receives exactly the same filtered view a human gets (its own cards +
public information) plus the variation's rules, and returns an action the
table accepts. At showdown the engine picks the bot's best legal cards using
the same rules that check humans' choices.

How it decides:
1. Estimate equity (share of the pot it expects to win) by simulation:
   deal random *unseen* cards to opponents and to the rest of the board, and
   score every player with the variation's row rules. Unseen = the deck minus
   our cards, the visible board and any cards already shown. Complex
   variations get fewer samples (there's a time budget).
2. Compare equity with the fair share and with pot odds.
3. Add position (button plays a little looser) and some randomness.
"""
from __future__ import annotations

import math
import random
import secrets
import time

from pokerkit import Card

from engine import evaluate as ev
from engine.variants import Variant


def _cards(strs) -> list[Card]:
    return ev.parse(strs)                      # understands jokers ("X1") too


_HU_CACHE: dict = {}


def _nice(amount: int) -> int:
    """Round a bet to the kind of number a person would pick."""
    if amount >= 200:
        return int(round(amount / 50) * 50)
    if amount >= 60:
        return int(round(amount / 10) * 10)
    return int(round(amount / 5) * 5) or amount


def _portion_hands(variant, hole, board):
    return ev.portion_hands(variant, ev.auto_declaration(variant, hole, board))


def estimate_equity(variant: Variant, hole, board: dict, opponents: int, known_dead,
                    samples: int, rng: random.Random, time_budget: float = 0.35) -> float:
    """Average share of the pot we'd win against random unseen hands."""
    if opponents <= 0:
        return 1.0
    used = set(hole) | {c for cs in board.values() for c in cs} | set(known_dead)
    unseen = [c for c in variant.deck if c not in used]
    missing = [(g.id, g.size - len(board.get(g.id, []))) for g in variant.board_groups]
    need_board = sum(n for _, n in missing)
    hole_n = variant.hole_card_count
    need = need_board + opponents * hole_n
    if need > len(unseen):
        return 1.0 / (opponents + 1)
    deadline = time.perf_counter() + time_budget
    total, done = 0.0, 0
    for s in range(samples):
        if s >= 4 and time.perf_counter() > deadline:
            break
        draw = rng.sample(unseen, need)
        full, k = {}, 0
        for gid, n in missing:
            full[gid] = list(board.get(gid, [])) + draw[k:k + n]
            k += n
        mine = _portion_hands(variant, hole, full)
        opps = [_portion_hands(variant, draw[k + j * hole_n:k + (j + 1) * hole_n], full)
                for j in range(opponents)]
        share = 0.0
        for p, my in enumerate(mine):
            if my is None:
                continue
            best = max((o[p] for o in opps if o[p] is not None), default=None)
            if best is None or my > best:
                share += 1.0
            elif my == best:
                ties = sum(1 for o in opps if o[p] == my)
                share += 1.0 / (ties + 1)
        total += share / len(mine)
        done += 1
    return total / max(done, 1)


# Three personalities. All of them only ever take legal actions and only see
# their own cards; they differ in how well they read the cards and the odds.
#   noob    - misjudges hand strength, calls far too often, random bet sizes
#   amateur - sensible, straightforward, a little bluffing
#   tycoon  - simulates more, folds weak hands, sizes bets by strength,
#             uses position and semi-bluffs before the river
LEVELS = {
    # Preflop (human-like): judge the hand on its own (heads-up strength),
    # play it if it clears ``open`` (looser in late position, tighter vs big
    # raises), raise with ``raise_pf``+, and sometimes ``limp`` in for a look.
    # Postflop habits: ``sunk`` = calls more once a lot is invested; ``tilt``
    # = plays looser for a few hands after losing a big pot.
    "noob":    dict(samples=30,  budget=0.15, noise=0.16, position=0.0,  call_slack=-0.10,
                    raise_strong=0.35, bet_good=0.6, bluff=0.12, sticky=0.45, semibluff=0.0,
                    read=0.0, trap=0.0, sizes=(0.3, 0.5, 1.0, 1.5),
                    open=0.40, raise_pf=0.64, pf_aggr=0.35, limp=0.50, vs_raise=0.010,
                    sunk=0.10, tilt=0.06),
    "amateur": dict(samples=150, budget=0.35, noise=0.0,  position=0.03, call_slack=0.03,
                    raise_strong=0.75, bet_good=0.5, bluff=0.07, sticky=0.0, semibluff=0.0,
                    read=0.15, trap=0.0, sizes=(0.5, 0.66, 0.75),
                    open=0.50, raise_pf=0.60, pf_aggr=0.55, limp=0.12, vs_raise=0.030,
                    sunk=0.06, tilt=0.05),
    "tycoon":  dict(samples=400, budget=0.7,  noise=0.0,  position=0.05, call_slack=0.06,
                    raise_strong=0.85, bet_good=0.65, bluff=0.09, sticky=0.0, semibluff=0.10,
                    read=0.30, trap=0.20, sizes=None,     # sized by hand strength
                    open=0.515, raise_pf=0.565, pf_aggr=0.80, limp=0.06, vs_raise=0.040,
                    sunk=0.0, tilt=0.0)
}
LEVEL_LABELS = {"noob": "Noob", "amateur": "Amateur", "tycoon": "Tycoon"}


class BasicBot:
    def __init__(self, rng: random.Random | None = None, samples: int | None = None,
                 level: str = "amateur"):
        if level not in LEVELS:
            raise ValueError(f"unknown bot level {level!r}")
        self.level = level
        self.p = LEVELS[level]
        self.rng = rng or random.Random(secrets.randbits(64))
        self.samples = samples if samples is not None else self.p["samples"]
        self.last_reason = ""
        self.hand_no = None         # to notice a new hand
        self.hand_start = 0         # chips at the start of this hand
        self.tilt_hands = 0         # plays looser for a few hands after a big loss

    # ---- human-like bookkeeping ----------------------------------------
    def _new_hand_check(self, view, seat) -> None:
        if view.get("hand_no") == self.hand_no:
            return
        now = seat["stack"] + seat["bet"]
        if self.hand_no is not None and self.hand_start and now < 0.7 * self.hand_start \
                and self.p["tilt"]:
            self.tilt_hands = 3                      # just lost a big pot
        elif self.tilt_hands:
            self.tilt_hands -= 1
        self.hand_no, self.hand_start = view.get("hand_no"), now

    def _heads_up_strength(self, variant, hole) -> float:
        """How good the private cards are on their own: chance to beat ONE
        random hand. Cached, since the same starting hands come up often."""
        key = (variant.name, variant.special, tuple(sorted(map(repr, hole))))
        if key not in _HU_CACHE:
            if len(_HU_CACHE) > 20_000:
                _HU_CACHE.clear()
            _HU_CACHE[key] = estimate_equity(variant, hole, {}, 1, [], 160, self.rng,
                                             time_budget=0.25)
        return _HU_CACHE[key]

    def _preflop(self, view, variant, seat, hole, legal) -> tuple[str, int | None]:
        """Like a person: is this a hand worth playing from here, at this price?"""
        p = self.p
        bb = view["settings"]["big_blind"]
        to_call = legal["call"]
        r = self.rng.random()
        strength = self._heads_up_strength(variant, hole)
        if p["noise"]:
            strength += self.rng.gauss(0, p["noise"] / 3)
        # position: later (closer to the button) plays looser
        seats = [s for s in view["seats"] if not s["empty"] and s["status"] in ("in", "all-in")]
        n = len(seats)
        btn = view.get("button") or 0
        order = sorted(s["index"] for s in seats)
        clockwise = sorted(order, key=lambda i: (i - btn - 1) % len(view["seats"]))
        pos = clockwise.index(view["you"]) / max(1, n - 1)          # 0 = first, 1 = button
        need = p["open"] - (pos - 0.5) * 0.05
        if self.tilt_hands:
            need -= p["tilt"]
        # facing a raise: the bigger it is, the better the hand must be
        raise_size = (seat["bet"] + to_call) / max(1, bb)
        if raise_size > 2:
            need += p["vs_raise"] * math.log2(raise_size / 2) * 2
        can_raise = legal["raise_kind"] is not None

        def open_to() -> int:
            callers = sum(1 for s in seats if s["bet"] >= bb and s["index"] != view["you"])
            if to_call > bb:                                     # re-raise ~3x
                target = 3 * (seat["bet"] + to_call)
            else:                                                # open: 3 BB + 1 per caller
                target = (3 + max(0, callers - 1)) * bb
            target = _nice(target)
            return max(legal["min_to"], min(legal["max_to"], target))

        if can_raise and strength >= max(need, p["raise_pf"]) and r < p["pf_aggr"]:
            self.last_reason = f"{self.level} preflop {strength:.2f}: raising"
            return ("raise" if legal["raise_kind"] == "raise" else "bet"), open_to()
        if to_call == 0:
            self.last_reason = f"{self.level} preflop {strength:.2f}: checking"
            return "check", None
        if strength >= need:
            self.last_reason = f"{self.level} preflop {strength:.2f} >= {need:.2f}: calling"
            return "call", None
        if to_call <= bb and r < p["limp"]:                       # just to see a flop
            self.last_reason = f"{self.level}: limping in to see the flop"
            return "call", None
        self.last_reason = f"{self.level} preflop {strength:.2f} < {need:.2f}: folding"
        return ("fold", None) if legal["fold"] else ("check", None)

    def decide(self, view: dict, variant: Variant) -> tuple[str, int | None]:
        legal = view["legal"]
        if legal is None:
            raise ValueError("bot asked to act when it is not its turn")
        me = view["you"]
        seat = view["seats"][me]
        hole = _cards(seat["cards"])
        board = {gid: _cards(cs) for gid, cs in view["board"].items()}
        dead = _cards([c for s in view["seats"] if not s["empty"] and s["index"] != me
                       and s.get("cards") for c in s["cards"] if c])      # face-up / shown
        opponents = sum(1 for s in view["seats"] if not s["empty"] and s["index"] != me
                        and s["status"] in ("in", "all-in"))
        p = self.p
        self._new_hand_check(view, seat)
        if view.get("stage") == variant.stages[0].name:          # before any community cards
            return self._preflop(view, variant, seat, hole, legal)
        budget = 0.08 if getattr(self, "fast", False) else p["budget"]   # "Skip ahead"
        equity = estimate_equity(variant, hole, board, opponents, dead, self.samples,
                                 self.rng, time_budget=budget)
        if p["noise"]:                                   # noobs misread their hand
            equity = min(1.0, max(0.0, equity + self.rng.gauss(0, p["noise"])))
        if seat.get("is_button"):
            equity += p["position"]
        fair = 1.0 / (opponents + 1)
        pot = view["total_pot"]
        to_call = legal["call"]
        r = self.rng.random()
        river = view.get("stage") == "River"
        stack = seat["stack"]
        # Reading bets: a big bet usually means a strong hand, so our chances
        # against THAT player are lower than against a random hand.
        if to_call > 0 and p["read"]:
            bet_ratio = to_call / max(1, pot - to_call)
            equity *= 1 - p["read"] * min(1.0, bet_ratio)
        # Trap: tycoon sometimes just calls/checks with a monster (not on the river).
        if (p["trap"] and not river and equity > 0.85 and r < p["trap"]):
            self.last_reason = f"{self.level}: slow-playing a monster"
            return ("check", None) if to_call == 0 else ("call", None)

        def raise_to(fraction: float) -> int:
            target = seat["bet"] + to_call + int(fraction * (pot + to_call))
            target = _nice(target)                          # human-style round amounts
            lo, hi = legal["min_to"], legal["max_to"]
            target = max(lo, min(hi, target))
            if target >= 0.7 * hi:
                target = hi
            return target

        def size() -> float:
            if p["sizes"]:
                return self.rng.choice(p["sizes"])
            return 0.4 + 0.6 * min(1.0, max(0.0, (equity - fair) / (1 - fair + 1e-9)))

        # Multi-way: with more opponents, demand a bit more before betting.
        crowd = 1.0 + (0.08 * max(0, opponents - 2) if p["read"] else 0.0)
        strong = equity > max(0.5, fair * 1.8 * crowd)
        good = equity > fair * 1.3 * crowd
        can_raise = legal["raise_kind"] is not None
        # Bluff mostly heads-up / three-way, a little more in position.
        bluff = p["bluff"] * (1.0 if opponents <= 2 else 0.4) * (1.3 if seat.get("is_button") else 1.0)
        if river and p["read"] and not strong:
            good = good and equity > 0.6      # river value bets need a real hand

        if to_call == 0:
            if can_raise and (strong or (good and r < p["bet_good"]) or r < bluff):
                self.last_reason = f"{self.level} eq {equity:.2f}: betting"
                return legal["raise_kind"], raise_to(size())
            self.last_reason = f"{self.level} eq {equity:.2f}: checking"
            return "check", None
        # Stack sense: don't call off a big part of the stack with a weak hand.
        if (p["read"] and to_call >= 0.4 * (stack + seat["bet"]) and equity < 0.45
                and legal["fold"]):
            self.last_reason = f"{self.level}: too expensive for this hand"
            return "fold", None

        pot_odds = to_call / (pot + to_call)
        # human habits: "I've put too much in to fold now", and tilt after a bad beat
        slack = p["call_slack"]
        invested = self.hand_start - (stack + seat["bet"]) + seat["bet"]
        if self.hand_start and invested >= 0.25 * self.hand_start:
            slack -= p["sunk"]
        if self.tilt_hands:
            slack -= p["tilt"]
            bluff *= 1.5
        if can_raise and strong and r < p["raise_strong"]:
            self.last_reason = f"{self.level} eq {equity:.2f} vs odds {pot_odds:.2f}: raising"
            return "raise", raise_to(size())
        if (can_raise and not river and p["semibluff"] and equity > fair
                and r < p["semibluff"]):
            self.last_reason = f"{self.level}: semi-bluff raise"
            return "raise", raise_to(0.6)
        if equity >= pot_odds + slack:
            self.last_reason = f"{self.level} eq {equity:.2f} vs odds {pot_odds:.2f}: calling"
            return "call", None
        if p["sticky"] and r < p["sticky"] and to_call <= 0.3 * (seat["stack"] + seat["bet"]):
            self.last_reason = f"{self.level}: can't let go, calling"
            return "call", None
        self.last_reason = f"{self.level} eq {equity:.2f} vs odds {pot_odds:.2f}: folding"
        return ("fold", None) if legal["fold"] else ("check", None)
