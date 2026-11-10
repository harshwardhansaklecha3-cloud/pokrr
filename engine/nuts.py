"""The nuts (best possible hand) and the second-best possible hand, for the
learning hints. Uses ONLY public information: the community cards, the
special card and the variation's rules - never anyone's private cards.

How: walk through every possible hand value from the top (straight flushes,
then four of a kind, ...) and stop at the first two values some player could
hold. A value is possible if some concrete 5 cards make it under the row's
rules: community cards from the row, the row's free jokers (Elevator floors),
and private cards that are still unseen (or anything, when private cards can
be wild because of a Joker / Jumping-joker special card).
"""
from __future__ import annotations

import itertools
import math

from pokerkit import Card

from . import evaluate as ev
from .variants.base import RANKS, Variant

SUITS = "shdc"
_CARD = {(r, s): next(Card.parse(RANKS[r] + s)) for r in range(13) for s in SUITS}
_RANK_OF = {c: r for (r, s), c in _CARD.items()}
DESC = list(range(12, -1, -1))
MAX_CHECKS = 400_000


def _windows():
    for top in range(12, 2, -1):
        yield [top - k for k in range(5)] if top != 3 else [3, 2, 1, 0, 12]


STRAIGHTS = [frozenset(w) for w in _windows()]


def _is_straight(ranks) -> bool:
    return frozenset(ranks) in STRAIGHTS


def _patterns():
    """(category, candidates) in descending hand value; each candidate list
    holds every concrete 5-card hand of exactly that value."""
    for win in _windows():                                    # straight flush
        yield [[_CARD[r, s] for r in win] for s in SUITS]
    for q in DESC:                                            # four of a kind
        for k in DESC:
            if k != q:
                yield [[_CARD[q, s] for s in SUITS] + [_CARD[k, t]] for t in SUITS]
    for t in DESC:                                            # full house
        for p in DESC:
            if p != t:
                yield [[_CARD[t, s] for s in a] + [_CARD[p, s] for s in b]
                       for a in itertools.combinations(SUITS, 3)
                       for b in itertools.combinations(SUITS, 2)]
    for ranks in itertools.combinations(DESC, 5):             # flush
        if not _is_straight(ranks):
            yield [[_CARD[r, s] for r in ranks] for s in SUITS]
    for win in _windows():                                    # straight
        yield [[_CARD[r, s] for r, s in zip(win, ss)]
               for ss in itertools.product(SUITS, repeat=5) if len(set(ss)) > 1]
    for t in DESC:                                            # three of a kind
        for k1, k2 in itertools.combinations([r for r in DESC if r != t], 2):
            yield [[_CARD[t, s] for s in a] + [_CARD[k1, x], _CARD[k2, y]]
                   for a in itertools.combinations(SUITS, 3) for x in SUITS for y in SUITS]
    for hi, lo in itertools.combinations(DESC, 2):            # two pair
        for k in DESC:
            if k not in (hi, lo):
                yield [[_CARD[hi, s] for s in a] + [_CARD[lo, s] for s in b] + [_CARD[k, x]]
                       for a in itertools.combinations(SUITS, 2)
                       for b in itertools.combinations(SUITS, 2) for x in SUITS]
    for p in DESC:                                            # one pair
        for ks in itertools.combinations([r for r in DESC if r != p], 3):
            yield [[_CARD[p, s] for s in a] + [_CARD[k, x] for k, x in zip(ks, xs)]
                   for a in itertools.combinations(SUITS, 2)
                   for xs in itertools.product(SUITS, repeat=3)]
    for ranks in itertools.combinations(DESC, 5):             # high card
        if not _is_straight(ranks):
            yield [[_CARD[r, s] for r, s in zip(ranks, ss)]
                   for ss in itertools.product(SUITS, repeat=5) if len(set(ss)) > 1]


def _row_top_two(variant: Variant, row, board: dict, raw_board: dict) -> list:
    """Up to two (hand, cards) of distinct value for this row, best first."""
    wild, dead = variant.special_effects(raw_board)
    g_ranks, g_cards = variant.global_wilds(raw_board)
    # someone's private card might be wild: special card, wild rule, jokers
    hole_wild = bool(wild or g_ranks or g_cards or variant.wild_rule == "jokers"
                     or variant.auction)
    visible = {ev.real(c) for cards in raw_board.values() for c in cards}
    group_of, extra_jokers = {}, 0
    for gi, gid in enumerate(row.groups):
        for c in board.get(gid, []):
            if isinstance(c, ev.Wild):
                extra_jokers += 1                   # a wild community card (scope "all")
            else:
                group_of[c] = gi
    J = row.jokers + extra_jokers
    avail = row.hole_alloc if row.hole_alloc is not None else variant.hole_card_count
    uses = [k for k in row.hole_use if k <= avail]
    dead_r = {RANKS.index(r) for r in dead}
    opg = row.one_per_group
    board_items = (len({group_of[c] for c in group_of}) if opg else len(group_of)) + J
    if not uses or max(uses) + board_items < 5:
        return []                            # this row can't make a hand yet

    def valid(H) -> bool:
        used_g, bh, extra, r_ok, r_bad = set(), 0, 0, 0, 0
        for c in H:
            g = group_of.get(c)
            if g is not None:
                if opg and g in used_g:
                    extra += 1
                else:
                    used_g.add(g)
                    bh += 1
            elif c in visible or (_RANK_OF[c] in dead_r and not hole_wild):
                r_bad += 1
            else:
                r_ok += 1
        for k in uses:
            for j in range(J + 1):
                b = 5 - k - j
                if b < 0 or b > bh:
                    continue
                if hole_wild:
                    return True
                if j >= r_bad + extra + (bh - b) and k <= r_ok:
                    return True
        return False

    min_k = min(uses) if uses else 0

    def is_their_best(H) -> bool:
        """Would a player holding these private cards really end up with H?
        (Not, say, a set of kings with a weaker kicker than the board gives.)"""
        if hole_wild:
            return True
        free = [c for c in H if c not in group_of and c not in visible]
        if len(free) < min_k:
            return True                      # rest of the holding: any blank cards
        value = ev._score_key(frozenset(H))
        for k in uses:                       # which of them are the private cards?
            for hole in itertools.combinations(free, k):
                res = ev.best_for_row(row, list(hole), board)
                if res is not None and res[0] == value:
                    return True
        return False

    # Rows where few community choices exist (Tic-tac-toe lines, Elevator
    # floors with 2 private cards...): simply try every possible holding.
    if not hole_wild and uses:
        unseen = [c for c in _RANK_OF if c not in visible and _RANK_OF[c] not in dead_r]
        m = max(uses)
        n_items = len(group_of)
        est = math.comb(len(unseen), m) * sum(
            math.comb(n_items, max(0, 5 - k - min(row.jokers, 5 - k))) for k in uses)
        if est <= 6_000:
            vals = {}
            for hole in itertools.combinations(unseen, m):
                res = ev.best_for_row(row, list(hole), board)
                if res is not None and res[0] not in vals:
                    vals[res[0]] = res
            top = sorted(vals, reverse=True)[:2]
            return [(h, list(h.cards)) for h in top]       # the 5 cards as played

    found, checks = [], 0
    for cands in _patterns():
        for H in cands:
            checks += 1
            if valid(H) and (not found or is_their_best(H)):
                found.append(H)
                break
        if len(found) == 2 or checks > MAX_CHECKS:
            break
    return [(ev._score_key(frozenset(H)), H) for H in found]


def top_two(variant: Variant, raw_board: dict) -> list[dict]:
    """[{"label", "cards", "row"}] for the best and second-best possible hands
    (per row in split-pot games; across all rows in best-row games)."""
    if not any(raw_board.get(g.id) for g in variant.board_groups if g.id != "special"):
        return []
    board = ev.prepare_board(variant, raw_board)
    per_row = []
    for row in variant.rows:
        if row.kind != "poker":
            continue
        per_row.append((row, _row_top_two(variant, row, board, raw_board)))
    out = []
    if variant.scoring == "split" and len(variant.rows) > 1:
        for row, top in per_row:
            for rank, (hand, cards) in zip(("nuts", "second"), top):
                out.append({"kind": rank, "row": row.label.split(" (")[0],
                            "label": variant.explain(hand).label,
                            "cards": [repr(c) for c in cards]})
        return out
    allh = sorted(((hand, cards, row) for row, top in per_row for hand, cards in top),
                  key=lambda x: x[0], reverse=True)
    picked = []
    for hand, cards, row in allh:
        if picked and hand == picked[-1][0]:
            continue
        picked.append((hand, cards, row))
        if len(picked) == 2:
            break
    multi = len(variant.rows) > 1
    for rank, (hand, cards, row) in zip(("nuts", "second"), picked):
        out.append({"kind": rank, "row": row.label.split(" (")[0] if multi else "",
                    "label": variant.explain(hand).label, "cards": [repr(c) for c in cards]})
    return out
