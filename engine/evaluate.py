"""Hand evaluation under a variation's row rules.

PokerKit ranks 5-card hands (``StandardHighHand``). This module decides
*which* 5 cards a player may use in each row, finds the best legal choice
(for bots / automatic rows), checks a human's declared choice, and handles
special cards:
- wild private cards (Joker / Jumping joker) are wrapped as ``Wild`` and
  become whatever card makes the hand best (any card not already in that
  5-card hand, so there is no "five of a kind");
- poisoned private cards are removed: they can't be used at all.

Declarations (what a player submits at showdown), per row id:
    {"hole": [card codes], "board": [card codes]}
- split-card variations with automatic selection: "hole" = the private cards
  given to that row (exactly hole_alloc of them); "board" is ignored.
- "declare" variations: "hole" + "board" = the exact 5 cards used.
A row where a player can't make any legal hand (e.g. poison + "fix 2")
gets NO_HAND, which loses to every real hand.
"""
from __future__ import annotations

import itertools
from functools import lru_cache

import pokerkit as pk
from pokerkit import Card

from .cards import STANDARD_52
from .variants.base import RANKS, HandRow, Variant

MAX_INDEX = 7461                                     # royal flush
NO_HAND = pk.StandardHighHand("7s5c4d3h2s")         # weakest possible hand


class DeclarationError(ValueError):
    """A player's card choice breaks the variation's rules."""


class Wild:
    """A private card that is wild. Shown as the real card; scores as any card."""
    __slots__ = ("card",)

    def __init__(self, card: Card):
        self.card = card

    def __repr__(self):
        return repr(self.card)


class JokerCard(pk.Card):
    """A real joker card (codes X1, X2 in the deck; X3 = the auction joker).
    Always wild, wherever it is. Each joker is its own card."""

    def __init__(self, n: int):
        # PokerKit can't show/muck "unknown" cards, so a joker carries an
        # ordinary rank/suit for PokerKit's bookkeeping only. It never equals
        # a real card, and our rules always treat it as a joker (is_joker).
        object.__setattr__(self, "rank", pk.Rank.ACE)
        object.__setattr__(self, "suit", pk.Suit.SPADE)
        object.__setattr__(self, "n", n)

    def __eq__(self, other):
        return other is self

    def __hash__(self):
        return hash(("joker", self.n))

    def __repr__(self):
        return f"X{self.n}"

    __str__ = __repr__


DECK_JOKERS = (JokerCard(1), JokerCard(2))
AUCTION_JOKER = JokerCard(3)
JOKER_BY_CODE = {repr(j): j for j in DECK_JOKERS + (AUCTION_JOKER,)}


def is_joker(c) -> bool:
    return isinstance(c, JokerCard)


class RowJoker(Wild):
    """A free joker that belongs to a row (Elevator floors). Not a real card."""
    __slots__ = ()

    def __init__(self):
        self.card = None

    def __repr__(self):
        return "Joker"


ROW_JOKER = RowJoker()


def row_jokers(row: HandRow, n_hole: int) -> tuple:
    """The row's free jokers used alongside ``n_hole`` private cards (always as
    many as fit: a wild card is never worse than the card it replaces)."""
    return (ROW_JOKER,) * max(0, min(row.jokers, 5 - n_hole))


def real(c) -> Card:
    return c.card if isinstance(c, Wild) else c


@lru_cache(maxsize=500_000)
def _score_key(key: frozenset) -> pk.StandardHighHand:
    return pk.StandardHighHand(tuple(key))


def _rank(c: Card) -> str:
    return getattr(c.rank, "value", str(c.rank))


def _card(ri: int, suit: str) -> Card:
    return next(Card.parse(RANKS[ri] + suit))


_SUITS = "shdc"


def _windows():
    """Straight rank windows, best first (A-high ... 5-high wheel)."""
    for top in range(12, 2, -1):
        yield top, ([top - k for k in range(5)] if top != 3 else [3, 2, 1, 0, 12])


def _wild_concrete(fixed: frozenset, w: int) -> frozenset:
    """The best real 5-card hand that ``fixed`` + ``w`` wild cards can make
    (wilds = any card not already in the hand, so no five of a kind).
    Checked category by category from the top; see test_wild_solver."""
    cards = list(fixed)
    n = len(cards)
    ri = [RANKS.index(_rank(c)) for c in cards]
    suits = {c.suit.value if hasattr(c.suit, "value") else str(c.suit) for c in cards}
    count = {r: ri.count(r) for r in range(13)}
    distinct = len(set(ri)) == n

    def fill(base: list, ranks_needed: list[int]) -> frozenset:
        out = set(base)
        for r in ranks_needed:
            out.add(next(_card(r, s) for s in _SUITS if _card(r, s) not in out))
        return frozenset(out)

    # straight flush
    if distinct and len(suits) <= 1:
        s = next(iter(suits)) if suits else "s"
        for _, win in _windows():
            if set(ri) <= set(win):
                return frozenset(_card(r, s) for r in win)
    # four of a kind
    for r in range(12, -1, -1):
        if 4 - count[r] <= w and n - count[r] <= 1:
            quad = [_card(r, s) for s in _SUITS]
            rest = [c for c in cards if RANKS.index(_rank(c)) != r]
            if rest:
                return frozenset(quad + rest)
            k = 12 if r != 12 else 11
            return frozenset(quad + [_card(k, "s")])
    # full house
    for t in range(12, -1, -1):
        for p in range(12, -1, -1):
            if p == t or count[t] > 3 or count[p] > 2 or count[t] + count[p] != n:
                continue
            if (3 - count[t]) + (2 - count[p]) == w:
                base = [c for c in cards]
                return fill(base, [t] * (3 - count[t]) + [p] * (2 - count[p]))
    # flush
    if distinct and len(suits) <= 1:
        s = next(iter(suits)) if suits else "s"
        extra = [r for r in range(12, -1, -1) if r not in ri][:w]
        return frozenset(cards + [_card(r, s) for r in extra])
    # straight
    if distinct:
        for _, win in _windows():
            if set(ri) <= set(win):
                return fill(cards, [r for r in win if r not in ri])
    # three of a kind (with wilds there is never a better two pair)
    for t in range(12, -1, -1):
        if count[t] + w >= 3 and count[t] <= 3:
            others = [r for r in ri if r != t]
            left = w - (3 - count[t])
            if len(set(others)) != len(others) or left < 0:
                continue
            kick = [r for r in range(12, -1, -1) if r != t and r not in others][:left]
            return fill(cards, [t] * (3 - count[t]) + kick)
    # one pair: one wild pairs the highest card
    top = max(ri)
    return fill(cards, [top])


@lru_cache(maxsize=200_000)
def _best_with_wilds(fixed: frozenset, w: int) -> pk.StandardHighHand:
    if 1 <= w <= 3 and fixed:
        return _score_key(_wild_concrete(fixed, w))
    return _best_with_wilds_slow(fixed, w)


def _best_with_wilds_slow(fixed: frozenset, w: int) -> pk.StandardHighHand:
    if w >= 4 or not fixed:
        # 4+ wild cards: the best hand is always a straight flush built
        # around the fixed card (or a royal flush if every card is wild).
        if not fixed:
            return _score_key(frozenset(pk.Card.parse("AsKsQsJsTs")))
        c = next(iter(fixed))
        suit = c.suit
        best = None
        ri = RANKS.index(_rank(c))
        for top in range(12, 2, -1):            # straights A-high .. 5-high (wheel)
            ranks = [top - k for k in range(5)] if top != 3 else [3, 2, 1, 0, 12]
            if ri in ranks:
                cards = frozenset(next(Card.parse(RANKS[x] + suit.value)) for x in ranks)
                h = _score_key(cards)
                if best is None or h > best:
                    best = h
        return best
    suits = {c.suit for c in fixed}
    ranks = {c.rank for c in fixed}
    cand = [c for c in STANDARD_52 if c not in fixed and (c.suit in suits or c.rank in ranks)]
    best = None
    for sub in itertools.combinations(cand, w):
        h = _score_key(fixed | frozenset(sub))
        if best is None or h > best:
            best = h
    return best


def score5(cards) -> pk.StandardHighHand:
    fixed = [c for c in cards if not isinstance(c, Wild)]
    w = len(cards) - len(fixed)
    if not w:
        return _score_key(frozenset(fixed))
    return _best_with_wilds(frozenset(fixed), w)


# ------------------------------------------------------------ other hand kinds
SHORT_DECK = tuple(c for c in STANDARD_52 if _rank(c) not in "2345")


@lru_cache(maxsize=200_000)
def _short_key(key: frozenset):
    return pk.ShortDeckHoldemHand(tuple(key))


@lru_cache(maxsize=100_000)
def _short_wild(fixed: frozenset, w: int):
    rest = [c for c in SHORT_DECK if c not in fixed]
    return max(_short_key(fixed | frozenset(s)) for s in itertools.combinations(rest, w))


def score_short(cards):
    """Short Deck (6+) ranking: flush beats full house, A-6-7-8-9 is a straight."""
    fixed = frozenset(c for c in cards if not isinstance(c, Wild))
    w = len(cards) - len(fixed)
    return _short_key(fixed) if not w else _short_wild(fixed, w)


@lru_cache(maxsize=200_000)
def _low_key(key: frozenset):
    try:
        return pk.EightOrBetterLowHand(tuple(key))
    except ValueError:
        return None                                  # not an 8-or-better low


@lru_cache(maxsize=100_000)
def _low_wild(fixed: frozenset, w: int):
    ranks = {_rank(c) for c in fixed}
    rest = [c for c in STANDARD_52 if c not in fixed and _rank(c) in "A2345678"
            and _rank(c) not in ranks]
    best = None
    for s in itertools.combinations(rest, w):
        h = _low_key(fixed | frozenset(s))
        if h is not None and (best is None or h > best):
            best = h
    return best


def score_low(cards):
    """8-or-better low (A-2-3-4-5 best), or None when the 5 cards don't qualify.
    Wild cards only help the POKER hand (owner, 2026-11-10): in the low a wild
    card counts as its printed card, and a joker (no printed card) can't be used.
    Free floor jokers (RowJoker) never appear in low rows."""
    plain = [real(c) for c in cards]
    if any(is_joker(c) or c is None for c in plain):
        return None
    return _low_key(frozenset(plain))


def scorer(kind: str):
    return {"short": score_short, "low8": score_low}.get(kind, score5)


BJ_VALUES = {"A": 1, "K": 10, "Q": 10, "J": 10, "T": 10}


def bj_total(cards) -> int:
    """Blackjack total of real cards: aces count 11 unless that busts."""
    total, aces = 0, 0
    for c in cards:
        r = _rank(real(c))
        total += BJ_VALUES.get(r, 0) or int(r)
        aces += r == "A"
    while aces and total + 10 <= 21:
        total += 10
        aces -= 1
    return total


class BJHand:
    """Closest to 21 without going over; ties go to the better poker hand."""
    __slots__ = ("total", "poker", "key")

    def __init__(self, total: int, poker):
        self.total, self.poker = total, poker
        self.key = (total, strength(poker))

    def __lt__(self, o): return self.key < o.key
    def __gt__(self, o): return self.key > o.key
    def __le__(self, o): return self.key <= o.key
    def __ge__(self, o): return self.key >= o.key
    def __eq__(self, o): return isinstance(o, BJHand) and self.key == o.key
    def __hash__(self): return hash(self.key)
    def __repr__(self): return f"BJ {self.total}"


# ------------------------------------------------------------ Teen Patti
# 3-card hands, highest first: Trail (three of a kind) > Pure sequence
# (straight flush) > Sequence > Color (flush) > Pair > High card.
# Sequences: A-K-Q is the highest, A-2-3 second, then K-Q-J ... 2-3-4.
_TP_LABELS = ["High card", "Pair", "Color", "Sequence", "Pure sequence", "Trail"]


class TeenPattiHand:
    __slots__ = ("key", "tp_label", "cards", "strength01")

    def __init__(self, key: tuple, cards: tuple):
        self.key = key
        self.cards = cards
        self.tp_label = _TP_LABELS[key[0]] if key[0] >= 0 else "No legal hand"
        self.strength01 = max(0.0, (key[0] + key[1] / 100) / 6) if key[0] >= 0 else -1.0

    def __lt__(self, o): return self.key < o.key
    def __gt__(self, o): return self.key > o.key
    def __le__(self, o): return self.key <= o.key
    def __ge__(self, o): return self.key >= o.key
    def __eq__(self, o): return isinstance(o, TeenPattiHand) and self.key == o.key
    def __hash__(self): return hash(self.key)
    def __repr__(self): return f"{self.tp_label} {self.cards}"


TP_NO_HAND = TeenPattiHand((-1, 0), ())


def _tp_key(cards) -> tuple:
    vals = sorted((RANKS.index(_rank(c)) for c in cards), reverse=True)   # A=12
    flush = len({c.suit for c in cards}) == 1
    if vals[0] == vals[1] == vals[2]:
        return (5, vals[0])
    seq = None
    if vals == [12, 11, 10]:
        seq = 100                                   # A-K-Q
    elif sorted(vals) == [0, 1, 12]:
        seq = 99                                    # A-2-3
    elif vals[0] - vals[1] == 1 and vals[1] - vals[2] == 1:
        seq = vals[0]
    if seq is not None:
        return (4 if flush else 3, seq)
    if flush:
        return (2, vals[0], vals[1], vals[2])
    if vals[0] == vals[1] or vals[1] == vals[2]:
        pair = vals[1]
        kicker = vals[2] if vals[0] == vals[1] else vals[0]
        return (1, pair, kicker)
    return (0, vals[0], vals[1], vals[2])


@lru_cache(maxsize=100_000)
def _tp_best(fixed: frozenset, w: int) -> TeenPattiHand:
    if w == 0:
        return TeenPattiHand(_tp_key(tuple(fixed)), tuple(fixed))
    if w >= 3:
        aces = tuple(Card.parse("AsAhAd"))
        return TeenPattiHand(_tp_key(aces), aces)
    best, best_cards = None, None
    cand = [c for c in STANDARD_52 if c not in fixed]
    for sub in itertools.combinations(cand, w):
        k = _tp_key(tuple(fixed) + sub)
        if best is None or k > best:
            best, best_cards = k, tuple(fixed) + sub
    return TeenPattiHand(best, best_cards)       # cards = as played (wilds substituted)


def joker_uses(hand, used) -> list[tuple]:
    """[(wild original card, card it plays as), ...] for the cards ``used``
    in an evaluated hand. ``hand.cards`` holds the cards as played."""
    fixed = {real(c) for c in used if not isinstance(c, Wild)}
    wilds = [c.card for c in used if isinstance(c, Wild)]
    subs = [c for c in hand.cards if c not in fixed]
    return list(zip(wilds, subs))


def score3(cards) -> TeenPattiHand:
    """Teen Patti 3-card hand. Wild cards only help the POKER hand (owner,
    2026-11-10): here a wild card counts as its printed card, and a hand with a
    joker in it (no printed card) loses to every real hand."""
    plain = [real(c) for c in cards]
    if any(is_joker(c) or c is None for c in plain):
        return TeenPattiHand((-1,), tuple(plain))
    return _tp_best(frozenset(plain), 0)


def parse_one(code):
    """A card from its code ('As', 'Td', ... or 'X1' for a joker)."""
    if not isinstance(code, str):
        return code
    if code in JOKER_BY_CODE:
        return JOKER_BY_CODE[code]
    return next(Card.parse(code))


def parse(codes) -> list[Card]:
    return [parse_one(c) for c in codes]


def _play(c, wild_ranks, dead_ranks, wild_cards):
    """How one card plays: None (poisoned), Wild(c), or c."""
    if is_joker(c):
        return Wild(c)
    r = _rank(c)
    if r in dead_ranks:
        return None
    if r in wild_ranks or repr(c) in wild_cards:
        return Wild(c)
    return c


def prepare(variant: Variant, hole, board: dict) -> list:
    """Private cards as they play right now: poisoned ones removed, wild ones
    wrapped (special card, wild-card rules, jokers)."""
    wild, dead = variant.special_effects(board)
    g_ranks, g_cards = variant.global_wilds(board)
    out = []
    for c in hole:
        p = _play(c, wild | g_ranks, dead, g_cards)
        if p is not None:
            out.append(p)
    return out


def prepare_board(variant: Variant, board: dict) -> dict:
    """Community cards as they play: the wild-card rule (deuces, one-eyed
    jacks, follow the queen, wild river, jokers) applies to them; the special
    card only when its scope is "all"."""
    g_ranks, g_cards = variant.global_wilds(board)
    scope_all = variant.special_scope == "all"
    has_joker = any(is_joker(c) for cs in board.values() for c in cs)
    if not (scope_all or g_ranks or g_cards or has_joker):
        return board
    wild, dead = variant.special_effects(board) if scope_all else (set(), set())
    out = {}
    for gid, cards in board.items():
        if gid == "special":
            out[gid] = cards
            continue
        out[gid] = [p for p in (_play(c, wild | g_ranks, dead, g_cards) for c in cards)
                    if p is not None]
    return out


def row_board(row: HandRow, board: dict) -> list[list[Card]]:
    return [list(board.get(g, [])) for g in row.groups]


def _board_choices(row: HandRow, groups: list[list[Card]], n: int):
    if n == 0:
        yield ()
        return
    if row.one_per_group:
        for chosen_groups in itertools.combinations([g for g in groups if g], n):
            yield from itertools.product(*chosen_groups)
    else:
        flat = [c for g in groups for c in g]
        yield from itertools.combinations(flat, n)


def best_for_row(row: HandRow, hole: list, board: dict):
    """Best legal (hand, hole_used, board_used) for this row, or None.
    ``hole``/``board`` should come from ``prepare``/``prepare_board``."""
    if row.kind == "teen_patti":
        best = None
        for h in itertools.combinations(hole, 3):
            hand = score3(h)
            if best is None or hand > best[0]:
                best = (hand, h, ())
        return best
    if row.kind == "bj21":
        return None                         # worked out from all private cards (fill_bj)
    score = scorer(row.kind)
    groups = row_board(row, board)
    best = None
    for k in row.hole_use:
        if k > len(hole):
            continue
        jk = row_jokers(row, k)
        for h in itertools.combinations(hole, k):
            for b in _board_choices(row, groups, 5 - k - len(jk)):
                hand = score(h + b + jk)
                if hand is not None and (best is None or hand > best[0]):
                    best = (hand, h, b + jk)
    return best


def fill_bj(variant: Variant, hole: list, out: dict) -> dict:
    """Blackjack Hold'em: the 21 row = all your private cards' total (bust =
    no hand); ties are broken by your poker hand."""
    for r in variant.rows:
        if r.kind != "bj21":
            continue
        total = bj_total(hole)
        poker = max((x[0] for k, x in out.items() if x and variant.row(k).kind == "poker"),
                    default=None)
        out[r.id] = (BJHand(total, poker), tuple(hole), ()) if total <= 21 else None
    return out


def check_row_choice(row: HandRow, hole_avail: list, board: dict,
                     hole_used: list, board_used: list) -> None:
    """Raise DeclarationError unless the 5 chosen cards are legal for the row."""
    if len(set(map(id, hole_used))) != len(hole_used) or len(set(board_used)) != len(board_used):
        raise DeclarationError(f"{row.label}: a card is chosen twice")
    jk = len(row_jokers(row, len(hole_used)))
    if len(hole_used) + len(board_used) + jk != 5:
        free = f" + {jk} free joker{'s' if jk > 1 else ''}" if jk else ""
        raise DeclarationError(f"{row.label}: choose exactly {5 - jk} cards{free} "
                               f"(you chose {len(hole_used) + len(board_used)})")
    if len(hole_used) not in row.hole_use:
        allowed = " or ".join(map(str, row.hole_use))
        raise DeclarationError(f"{row.label}: must use {allowed} private card(s), "
                               f"not {len(hole_used)}")
    if not all(any(h is a for a in hole_avail) for h in hole_used):
        raise DeclarationError(f"{row.label}: those private cards aren't available here")
    groups = row_board(row, board)
    all_board = [c for g in groups for c in g]
    if not set(board_used) <= set(all_board):
        raise DeclarationError(f"{row.label}: a chosen community card isn't in this row")
    if row.one_per_group:
        for g in groups:
            if len(set(g) & set(board_used)) > 1:
                raise DeclarationError(f"{row.label}: only one card from each group")


def strength(hand) -> float:
    if hand is None:
        return -1.0
    if isinstance(hand, TeenPattiHand):
        return hand.strength01
    if isinstance(hand, BJHand):
        return hand.total / 21
    return hand.entry.index / MAX_INDEX


def _assignments(hole: list, sizes: list[int]):
    def rec(i, remaining):
        if i == len(sizes):
            yield ()
            return
        for combo in itertools.combinations(remaining, sizes[i]):
            rest = [c for c in remaining if c not in combo]
            for tail in rec(i + 1, rest):
                yield (combo,) + tail
    yield from rec(0, list(hole))


def auto_declaration(variant: Variant, hole: list[Card], board: dict):
    """The bot / automatic choice: {row_id: (hand, hole_used, board_used) or None}.

    Split-card rows: tries every assignment of the real private cards. With
    "split" scoring it maximises total strength across rows; with "best"
    scoring it maximises the strongest row."""
    rows = variant.rows
    prep = prepare(variant, hole, board)
    board = prepare_board(variant, board)
    if not variant.split_hole_cards:
        return fill_bj(variant, hole, {r.id: best_for_row(r, prep, board) for r in rows})
    pmap = {real(e): e for e in prep}
    cache: dict = {}

    def best_sub(ri, sub):
        key = (ri, sub)
        if key not in cache:
            entries = [pmap[c] for c in sub if c in pmap]
            cache[key] = best_for_row(rows[ri], entries, board)
        return cache[key]

    best_choice, best_val = None, None
    for assign in _assignments(hole, [r.hole_alloc for r in rows]):
        results = [best_sub(i, tuple(sorted(a, key=repr))) for i, a in enumerate(assign)]
        vals = [strength(x[0] if x else None) for x in results]
        val = sum(vals) if variant.scoring == "split" else max(vals)
        if best_val is None or val > best_val:
            best_val, best_choice = val, results
    if best_choice is None:                 # not enough cards to split (can't happen in play)
        return {r.id: None for r in rows}
    return {r.id: res for r, res in zip(rows, best_choice)}


def apply_declaration(variant: Variant, hole: list[Card], board: dict, decl: dict) -> dict:
    """Validate a human declaration; return {row_id: (hand, hole, board) or None}."""
    if not isinstance(decl, dict):
        raise DeclarationError("declaration must be an object")
    raw_board = board
    prep = prepare(variant, hole, board)
    pmap = {real(e): e for e in prep}
    board = prepare_board(variant, board)
    bmap = {real(e): e for cards in board.values() for e in cards}
    out, used_hole = {}, []
    # Games where you pick your cards: rows left empty don't play. In
    # best-row games you claim ONE row (if you claim more, the strongest counts).
    picking = variant.selection == "declare"
    claimable = [r for r in variant.rows if r.kind != "bj21"]
    if picking and not any(isinstance(decl.get(r.id), dict) and
                           (decl[r.id].get("hole") or decl[r.id].get("board"))
                           for r in claimable):
        if any(v for k, v in auto_declaration(variant, hole, raw_board).items()
               if variant.row(k).kind != "bj21"):
            raise DeclarationError("claim a hand in at least one row")
    for row in claimable:
        part = decl.get(row.id)
        # An empty claim gives up that row / part of the pot (one-row games:
        # the rows you don't claim; or when poison leaves no legal hand there).
        if picking and not (isinstance(part, dict) and (part.get("hole") or part.get("board"))):
            out[row.id] = None
            continue
        if not isinstance(part, dict):
            raise DeclarationError(f"{row.label}: no choice made")
        try:
            h = parse(part.get("hole", []))
            b = parse(part.get("board", []))
        except (ValueError, StopIteration, TypeError):
            raise DeclarationError(f"{row.label}: unreadable card") from None
        if not set(h) <= set(hole):
            raise DeclarationError(f"{row.label}: that isn't one of your cards")
        if len(set(h)) != len(h):
            raise DeclarationError(f"{row.label}: a card is chosen twice")
        if variant.split_hole_cards:
            if variant.selection == "auto":
                if len(h) != row.hole_alloc:
                    raise DeclarationError(f"{row.label}: give exactly {row.hole_alloc} "
                                           "of your cards to this row")
            elif len(h) > row.hole_alloc:
                raise DeclarationError(f"{row.label}: at most {row.hole_alloc} "
                                       "private cards in this row")
            if set(h) & set(used_hole):
                raise DeclarationError("each private card can only go to one row")
            used_hole += h
        if variant.selection == "auto":
            out[row.id] = best_for_row(row, [pmap[c] for c in h if c in pmap], board)
        else:
            poisoned = [c for c in h if c not in pmap]
            if poisoned:
                raise DeclarationError(f"{row.label}: {poisoned[0]!r} is poisoned and "
                                       "can't be used")
            entries = [pmap[c] for c in h]
            if row.kind == "teen_patti":
                if len(entries) != 3 or b:
                    raise DeclarationError(f"{row.label}: choose exactly 3 of your cards")
                out[row.id] = (score3(tuple(entries)), tuple(entries), ())
                continue
            missing = [c for c in b if c not in bmap]
            if missing:
                raise DeclarationError(f"{row.label}: {missing[0]!r} is poisoned or not on "
                                       "the table")
            bentries = [bmap[c] for c in b]
            check_row_choice(row, prep, board, entries, bentries)
            jk = row_jokers(row, len(entries))
            hand = scorer(row.kind)(tuple(entries) + tuple(bentries) + jk)
            if hand is None:
                raise DeclarationError(f"{row.label}: those 5 cards aren't an 8-or-better low "
                                       "(5 different cards, 8 or lower). Leave it empty if "
                                       "you have no low.")
            out[row.id] = (hand, tuple(entries), tuple(bentries) + jk)
    return fill_bj(variant, hole, out)


SHORT_NO_HAND = pk.ShortDeckHoldemHand("Js9d8c7h6s")   # weakest Short Deck hand


def no_hand(kind: str):
    """What a player without a legal hand reports for a row kind. None means
    "not eligible for this part of the pot" (no low / bust)."""
    return {"teen_patti": TP_NO_HAND, "short": SHORT_NO_HAND, "poker": NO_HAND}.get(kind)


def portion_hands(variant: Variant, row_results: dict) -> list:
    """What PokerKit compares for each pot portion (NO_HAND if none)."""
    hands = [row_results[r.id][0] if row_results.get(r.id) else no_hand(r.kind)
             for r in variant.rows]
    if variant.scoring == "split":
        return hands
    return [max((h for h in hands if h is not None), default=None)]
