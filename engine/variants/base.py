"""What a POKRR variation is: a small "recipe" made of a few building blocks.

Building blocks (enough for every variation agreed so far):

- deck                      which cards are in play
- stages                    betting rounds, and what is dealt/revealed before each
- board groups              sets of community cards (a flop row, a shared turn...)
                            with a grid position for the table layout
- hand rows                 each row is one 5-card poker hand made from:
    groups                    the board groups this row may use
                              (a group can belong to several rows = shared cards)
    hole_use                  allowed numbers of private cards: (2,) = "fix 2",
                              (0, 1, 2) = "012", (3,) = exactly 3, ...
    hole_alloc                None = all private cards usable in this row;
                              k = player must give k private cards to this row
                              only (split before showdown; Elevator pairs)
    one_per_group             at most one card from each group (Pyramid)
- scoring                   "split": the pot is divided equally between rows
                            "best":  the single best row-hand wins the whole pot
- selection                 "auto": the engine finds each player's best legal hand
                            "declare": human players pick their own cards
                            (a worse pick counts); bots pick the best

Anything that can't be expressed this way gets a small code module, not a
bigger rules language.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pokerkit as pk
from pokerkit import Card

RANKS = "23456789TJQKA"

# Special cards: one extra card turned up at a chosen stage, set apart from
# the board (not part of any row). It changes what PRIVATE cards do:
#   joker   - private cards of its rank are wild
#   poison  - private cards of its rank can't be used
#   jumping - its rank is poison; ranks one above/below are wild (A wraps to 2)
SPECIAL_KINDS = {"joker": "Joker", "poison": "Poison", "jumping": "Jumping joker"}


class VariantError(ValueError):
    """The variation definition, or its use with this table, is invalid."""


@dataclass(frozen=True)
class BoardGroup:
    id: str
    label: str
    size: int
    row: int = 0          # layout grid row (0 = top)
    col: int = 0          # layout grid column
    row_span: int = 1     # >1 for cards shared by several rows (shown between them)
    hidden: bool = False  # never shown as a group (Dice replacement cards)
    optional: bool = False  # may stay empty (Red River's extra rivers)


@dataclass(frozen=True)
class Stage:
    """One betting round, plus what is dealt right before it."""
    name: str
    hole_cards: int = 0            # cards dealt to each player at this stage
    reveal: tuple[str, ...] = ()   # board-group ids revealed (in this order)
    burn: bool = False             # burn one card before revealing
    hole_up: bool = False          # those cards are dealt face UP (everyone sees
                                   # them, only their owner can use them)


@dataclass(frozen=True)
class HandRow:
    id: str
    label: str
    groups: tuple[str, ...]
    hole_use: tuple[int, ...]
    hole_alloc: int | None = None
    one_per_group: bool = False
    kind: str = "poker"            # "poker" (best 5 cards) | "teen_patti" (3 cards)
                                   # | "short" (Short Deck ranking) | "low8" (8-or-better
                                   # low) | "bj21" (closest to 21, Blackjack Hold'em)
    jokers: int = 0                # free wild cards that belong to this row
                                   # (Elevator floors); always played, as any card


@dataclass(frozen=True)
class HandExplanation:
    label: str
    cards: tuple[Card, ...]


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    summary: tuple[str, ...]
    deck: tuple[Card, ...]
    stages: tuple[Stage, ...]
    board_groups: tuple[BoardGroup, ...]
    rows: tuple[HandRow, ...]
    scoring: str = "split"         # "split" | "best"
    selection: str = "auto"        # "auto" | "declare"
    min_players: int = 2
    max_players: int = 10
    betting: pk.BettingStructure = pk.BettingStructure.NO_LIMIT
    options: tuple[tuple[str, str], ...] = ()   # chosen preset options
    special: tuple | None = None   # (kind, stage name, scope "private"|"all") or None
    passing: tuple[str, ...] = ()  # Anaconda: pass 1 card left after these stages
    pass_mode: str = "pass"        # "pass" (Anaconda) | "discard" (Pineapple)
    pass_count: int = 1            # cards passed / thrown away each time
    dice: bool = False             # Dice add-on: die swaps a community card
    red_river: int = 0             # extra rivers available (Red River)
    blackjack: bool = False        # hit/stand phase after the flop (Blackjack Hold'em)
    market: tuple = ()             # (cards on offer, buys each) - Wall Street
    wild_rule: str = ""            # "" | deuces | oneeyed | jokers | queen | river
    auction: bool = False          # Joker auction after the flop betting
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def special_scope(self) -> str:
        return self.special[2] if self.special and len(self.special) > 2 else "private"

    def special_effects(self, board: dict) -> tuple[set[str], set[str]]:
        """(wild ranks, dead ranks) once the special card is face up.
        Ranks are 'A', 'K', ..., '2'."""
        if not self.special:
            return set(), set()
        cards = board.get("special") or []
        if not cards:
            return set(), set()
        rank = cards[0].rank
        r = getattr(rank, "value", str(rank))
        kind = self.special[0]
        if kind == "joker":
            return {r}, set()
        if kind == "poison":
            return set(), {r}
        i = RANKS.index(r)
        return {RANKS[(i - 1) % 13], RANKS[(i + 1) % 13]}, {r}

    def global_wilds(self, board: dict) -> tuple[set[str], set[str]]:
        """(wild ranks, wild card codes) from the wild-card rule. These apply
        to EVERY card - private and community. (Real jokers are always wild.)"""
        rule = self.wild_rule
        if rule == "deuces":
            return {"2"}, set()
        if rule == "oneeyed":
            return set(), {"Js", "Jh", "Kh"}
        if rule in ("queen", "river"):
            def rank(c):
                if repr(c).startswith("X"):            # a joker has no rank of its own
                    return "?"
                return getattr(c.rank, "value", str(c.rank))
            if rule == "queen":
                seq = [c for gid in self.board_order() if gid not in ("special", "dice")
                       for c in board.get(gid, [])]
                wild = {"Q"}
                for i, c in enumerate(seq):
                    if rank(c) == "Q" and i + 1 < len(seq) and rank(seq[i + 1]) != "Q":
                        wild = {"Q", rank(seq[i + 1])}          # the latest queen's follower
                    elif rank(c) == "Q" and i + 1 >= len(seq):
                        wild = {"Q"}                            # a queen came last: queens only
                return wild, set()
            # wild river: the rank(s) of the river once it's out
            stages = [s for s in self.stages
                      if any(g not in ("special", "dice") for g in s.reveal)]
            if not stages:
                return set(), set()
            if self.red_river:
                for s in reversed(stages):
                    cards = [c for g in s.reveal if g not in ("special", "dice")
                             for c in board.get(g, [])]
                    if cards and s.name.startswith("River"):
                        return {rank(c) for c in cards}, set()
                return set(), set()
            cards = [c for g in stages[-1].reveal if g not in ("special", "dice")
                     for c in board.get(g, [])]
            return {rank(c) for c in cards}, set()
        return set(), set()

    @property
    def has_wilds(self) -> bool:
        return bool(self.wild_rule or self.special or self.auction)

    # ---- derived facts -------------------------------------------------
    @property
    def hole_card_count(self) -> int:
        return sum(s.hole_cards for s in self.stages)

    @property
    def board_card_count(self) -> int:
        return sum(g.size for g in self.board_groups)

    @property
    def burn_count(self) -> int:
        return sum(1 for s in self.stages if s.burn)

    @property
    def split_hole_cards(self) -> bool:
        return any(r.hole_alloc is not None for r in self.rows)

    @property
    def needs_declaration(self) -> bool:
        """Humans must make a choice at showdown (split cards or pick cards)."""
        return self.selection == "declare" or self.split_hole_cards

    @property
    def portions(self) -> int:
        """How many equal parts each pot is divided into."""
        return len(self.rows) if self.scoring == "split" else 1

    def group(self, group_id: str) -> BoardGroup:
        for g in self.board_groups:
            if g.id == group_id:
                return g
        raise VariantError(f"{self.id}: unknown board group {group_id!r}")

    def row(self, row_id: str) -> HandRow:
        for r in self.rows:
            if r.id == row_id:
                return r
        raise VariantError(f"{self.id}: unknown row {row_id!r}")

    def board_order(self) -> tuple[str, ...]:
        """Group ids in the order their cards are dealt onto the board."""
        return tuple(gid for s in self.stages for gid in s.reveal)

    # ---- validation ------------------------------------------------------
    def validate(self, player_count: int | None = None) -> None:
        """Raise VariantError if the definition or player count is unusable."""
        if len(set(self.deck)) != len(self.deck):
            raise VariantError(f"{self.id}: deck has duplicate cards")
        if not self.stages:
            raise VariantError(f"{self.id}: needs at least one stage")
        if self.stages[0].burn:
            raise VariantError(f"{self.id}: first stage must not burn a card")
        if self.stages[0].hole_cards <= 0:
            raise VariantError(f"{self.id}: players need private cards before the first round")
        if self.passing:
            names = [s.name for s in self.stages]
            allowed = names if self.pass_mode == "discard" else names[1:]
            if any(p not in allowed for p in self.passing):
                raise VariantError(f"{self.id}: card passing must follow a betting round")
            if self.pass_mode == "pass" and self.stages[0].hole_cards < 2:
                raise VariantError("Anaconda needs at least 2 private cards")
            if self.pass_mode == "discard":
                left = self.hole_card_count - len(self.passing) * self.pass_count
                for r in self.rows:
                    need = (3 if r.kind == "teen_patti" else min(r.hole_use)) \
                        if r.kind != "bj21" else 0
                    if left < need or (r.hole_alloc and left < sum(x.hole_alloc or 0
                                                                   for x in self.rows)):
                        raise VariantError(
                            f"Pineapple: throwing away {len(self.passing) * self.pass_count} "
                            f"card(s) leaves too few for {self.name} — choose fewer throws "
                            "or a game with more private cards")
        ids = [g.id for g in self.board_groups]
        if len(set(ids)) != len(ids):
            raise VariantError(f"{self.id}: duplicate board group ids")
        if any(g.size <= 0 for g in self.board_groups):
            raise VariantError(f"{self.id}: board groups must have at least one card")
        if sorted(self.board_order()) != sorted(ids):
            raise VariantError(f"{self.id}: every board group must be revealed exactly once")
        if not self.rows:
            raise VariantError(f"{self.id}: needs at least one hand row")
        if self.scoring not in ("split", "best") or self.selection not in ("auto", "declare"):
            raise VariantError(f"{self.id}: bad scoring/selection")
        allocs = [r.hole_alloc for r in self.rows]
        if any(a is not None for a in allocs):
            if any(a is None for a in allocs):
                raise VariantError(f"{self.id}: either every row gets its own private "
                                   "cards or none does")
            if sum(allocs) > self.hole_card_count:
                raise VariantError(f"{self.id}: rows need more private cards than are dealt")
        for r in self.rows:
            for gid in r.groups:
                self.group(gid)
            avail_hole = r.hole_alloc if r.hole_alloc is not None else (
                self.hole_card_count + (self.market[1] if self.market else 0))
            if r.kind == "bj21":
                continue
            if r.kind == "teen_patti":
                if r.groups or r.hole_use != (3,) or avail_hole < 3:
                    raise VariantError(f"{self.id}: a Teen Patti row is exactly 3 private cards")
                continue
            avail_board = (len(r.groups) if r.one_per_group
                           else sum(self.group(g).size for g in r.groups)) + r.jokers
            if not any(0 <= k <= avail_hole and 0 <= 5 - k <= avail_board for k in r.hole_use):
                raise VariantError(f"{self.id}: row {r.label} can never make a 5-card hand")
        if not 2 <= self.min_players <= self.max_players:
            raise VariantError(f"{self.id}: bad player limits")
        if player_count is not None:
            if not self.min_players <= player_count <= self.max_players:
                raise VariantError(
                    f"{self.name} needs {self.min_players}-{self.max_players} "
                    f"players; {player_count} are seated")
            needed = (player_count * self.hole_card_count
                      + self.board_card_count + self.burn_count
                      + (self.market[0] + player_count * self.market[1] if self.market else 0))
            if needed > len(self.deck):
                raise VariantError(
                    f"{self.name} needs {needed} cards for {player_count} "
                    f"players but the deck has {len(self.deck)}")

    # ---- PokerKit translation -------------------------------------------
    def pokerkit_streets(self, big_blind: int) -> tuple[pk.Street, ...]:
        return tuple(pk.Street(
            card_burning_status=s.burn,
            hole_dealing_statuses=(s.hole_up,) * s.hole_cards,
            board_dealing_count=sum(self.group(g).size for g in s.reveal),
            draw_status=False,
            opening=pk.Opening.POSITION,
            min_completion_betting_or_raising_amount=big_blind,
            max_completion_betting_or_raising_count=None,
        ) for s in self.stages)

    def split_board(self, board: list[Card]) -> dict[str, list[Card]]:
        """Map the flat dealt board back to its groups (partially dealt ok)."""
        out: dict[str, list[Card]] = {g.id: [] for g in self.board_groups}
        i = 0
        for gid in self.board_order():
            n = self.group(gid).size
            out[gid] = list(board[i:i + n])
            i += n
        return out

    def with_passing(self, mode: str) -> "Variant":
        """Anaconda add-on: after the flop betting (mode "flop") or after every
        betting round from the flop on (mode "every"), each player still in the
        hand passes 1 private card to the next player on their left."""
        later = [s.name for s in self.stages[1:]]
        if not later:
            raise VariantError(f"{self.name} has only one betting round: no Anaconda")
        if mode == "flop":
            after = (later[0],)
            text = "ANACONDA: after the flop betting, everyone passes 1 private card to the player on their left."
        elif mode == "every":
            after = tuple(later)
            text = ("ANACONDA: after every betting round from the flop on, everyone passes "
                    "1 private card to the player on their left.")
        else:
            raise VariantError(f"unknown Anaconda mode {mode!r}")
        return replace(self, passing=after, summary=self.summary + (text,))

    def with_pineapple(self, mode: str, count: int = 1) -> "Variant":
        """Pineapple add-on: after a betting round everyone still in the hand
        throws away ``count`` private card(s), face down. "preflop" = classic
        Pineapple, "flop" = Crazy Pineapple / Irish, "every" = after every
        betting round except the last."""
        if self.passing:
            raise VariantError("choose Anaconda or Pineapple, not both")
        if count not in (1, 2):
            raise VariantError("Pineapple throws away 1 or 2 cards")
        names = [s.name for s in self.stages]
        if len(names) < 2:
            raise VariantError(f"{self.name} has only one betting round: no Pineapple")
        if mode == "preflop":
            after, when = (names[0],), "after the preflop betting"
        elif mode == "flop":
            after, when = (names[1],), "after the flop betting"
        elif mode == "every":
            after, when = tuple(names[:-1]), "after every betting round (except the last)"
        else:
            raise VariantError(f"unknown Pineapple mode {mode!r}")
        n = "1 private card" if count == 1 else "2 private cards"
        text = f"PINEAPPLE: {when}, everyone still in the hand throws away {n} (face down)."
        # Too few cards left to play after throwing? Deal just enough extra
        # private cards at the start (owner, 2026-11-10: "only when needed").
        left = self.hole_card_count - len(after) * count
        need = 0
        for r in self.rows:
            if r.kind == "bj21":
                continue
            need = max(need, 3 if r.kind == "teen_patti" else min(r.hole_use))
        need = max(need, sum(r.hole_alloc or 0 for r in self.rows))
        stages = self.stages
        if left < need:
            extra = need - left
            stages = (replace(stages[0], hole_cards=stages[0].hole_cards + extra),) + stages[1:]
            text += (f" To make room, everyone is dealt {extra} extra private "
                     f"card{'s' if extra > 1 else ''} ({stages[0].hole_cards} at the start).")
        v = replace(self, passing=after, pass_mode="discard", pass_count=count, stages=stages,
                    summary=self.summary + (text,))
        return v

    def with_dice(self) -> "Variant":
        """Dice add-on: once every community card is out, a die is rolled
        for each group of up to 5 community cards (in dealing order): a roll
        of N replaces the Nth card with a new one; a roll past the end (6 on
        a 5-card board) changes nothing. Then one more betting round."""
        if self.red_river:
            raise VariantError("Dice can't be combined with Red River")
        n = sum(g.size for g in self.board_groups if g.id != "special")
        if n == 0:
            raise VariantError(f"{self.name} has no community cards for the dice")
        chunks = -(-n // 5)
        group = BoardGroup("dice", "Dice", chunks, hidden=True, col=99)
        text = ("DICE: after the last community card a die is rolled" +
                (" for each group of 5 community cards (in dealing order)" if chunks > 1 else "")
                + ": a 4 replaces the 4th card with a new one, a 6 changes nothing. "
                "Then one more betting round.")
        return replace(self, board_groups=self.board_groups + (group,), dice=True,
                       stages=self.stages + (Stage("Dice", reveal=("dice",)),),
                       summary=self.summary + (text,))

    def dice_positions(self) -> list[list[tuple[str, int]]]:
        """Community-card positions in dealing order, in groups of 5."""
        order = [(gid, i) for gid in self.board_order() if gid not in ("special", "dice")
                 for i in range(self.group(gid).size)]
        return [order[k:k + 5] for k in range(0, len(order), 5)]

    DECKS = {"short": ("Short deck", "6789TJQKA",
                       "SHORT DECK: 36 cards (no 2s, 3s, 4s or 5s). A FLUSH BEATS A FULL HOUSE, "
                       "and A-6-7-8-9 is a straight."),
             "royal": ("Royal deck", "TJQKA",
                       "ROYAL DECK: only the 10s, jacks, queens, kings and aces (20 cards). "
                       "Normal hand ranking; the only straight is A-K-Q-J-10.")}

    def with_deck(self, kind: str) -> "Variant":
        """The same game with a smaller deck (owner, 2026-11-10). Short deck
        also switches poker hands to Short Deck ranking."""
        if kind == "standard":
            return self
        if kind not in self.DECKS:
            raise VariantError(f"unknown deck {kind!r}")
        label, ranks, text = self.DECKS[kind]
        if any(r.kind == "low8" for r in self.rows):
            raise VariantError(f"{self.name} needs low cards (A-8) for the low hand")
        deck = tuple(c for c in self.deck if repr(c)[0] in ranks)
        rows = self.rows
        if kind == "short":
            rows = tuple(replace(r, kind="short") if r.kind == "poker" else r for r in rows)
        return replace(self, deck=deck, rows=rows, name=f"{self.name} · {label}",
                       summary=(text,) + self.summary)

    WILD_TEXT = {
        "deuces": ("Deuces wild", "DEUCES WILD: every 2 — private or community — is wild."),
        "oneeyed": ("One-eyed jacks", "ONE-EYED JACKS: J♠, J♥ and the suicide king K♥ are wild, "
                    "private or community."),
        "jokers": ("Jokers in the deck", "JOKERS: 2 jokers are added to the deck (54 cards). A "
                   "joker in your hand is your wild card; a joker on the board is wild for everyone."),
        "queen": ("Follow the Queen", "FOLLOW THE QUEEN: queens are wild. When a queen hits the "
                  "board, the rank of the NEXT board card becomes wild too (for every card). A new "
                  "queen changes it; a queen as the last card leaves just queens wild."),
        "river": ("Wild river", "WILD RIVER: once the river is out, every card of the river's "
                  "rank is wild — private or community."),
    }

    def with_wild_rule(self, rule: str) -> "Variant":
        if rule not in self.WILD_TEXT:
            raise VariantError(f"unknown wild-card rule {rule!r}")
        if rule == "jokers" and self.blackjack:
            raise VariantError("jokers can't be counted in Blackjack Hold'em's 21")
        if rule in ("queen", "river") and not any(
                g for s in self.stages for g in s.reveal if g not in ("special", "dice")):
            raise VariantError(f"{self.WILD_TEXT[rule][0]} needs community cards")
        deck = self.deck
        if rule == "jokers":
            from ..evaluate import DECK_JOKERS
            deck = self.deck + DECK_JOKERS
        return replace(self, wild_rule=rule, deck=deck,
                       summary=self.summary + (self.WILD_TEXT[rule][1],))

    def with_auction(self) -> "Variant":
        """Joker auction: after the flop betting a face-up joker is auctioned;
        the winner pays the pot and keeps it as a wild private card."""
        if len(self.stages) < 3 or self.split_hole_cards or self.blackjack or self.market:
            raise VariantError(f"the Joker auction doesn't fit {self.name}")
        return replace(self, auction=True, summary=self.summary + (
            "JOKER AUCTION: after the flop betting a joker goes up for auction. In turn, bid "
            "more (at least 1 big blind more) or drop out. The top bidder pays their bid into "
            "the pot and gets the joker as a face-up WILD private card.",))

    def with_claims(self) -> "Variant":
        """Every player claims their own hand at showdown (a weaker claim
        counts). Bots always claim their best."""
        if self.selection == "declare":
            return self
        text = ("SHOWDOWN: you claim your own hand — pick the exact cards. A weaker claim "
                "counts, so read your hand carefully!")
        if self.scoring == "best" and len(self.rows) > 1:
            text += " Claim ONE row; the best claim wins the pot."
        return replace(self, selection="declare", summary=self.summary + (text,))

    def with_special(self, kind: str, stage: str, scope: str = "private") -> "Variant":
        """This variation plus a Joker / Poison / Jumping-joker card turned
        up at ``stage`` (Flop, Turn or River). ``scope`` "all" makes it affect
        community cards too."""
        if kind not in SPECIAL_KINDS:
            raise VariantError(f"unknown special card {kind!r}")
        if scope not in ("private", "all"):
            raise VariantError(f"unknown special-card scope {scope!r}")
        if stage not in [s.name for s in self.stages[1:]] or not self.board_groups:
            raise VariantError(f"{self.name} has no {stage!r} stage for a special card")
        last_col = max(g.col for g in self.board_groups)
        n_rows = max(g.row + g.row_span for g in self.board_groups)
        label = {"joker": "Joker", "poison": "Poison",
                 "jumping": "Poison (±1 = jokers)"}[kind]
        group = BoardGroup("special", label, 1, row=0, col=last_col + 1, row_span=n_rows)
        stages = tuple(replace(s, reveal=s.reveal + ("special",)) if s.name == stage else s
                       for s in self.stages)
        when = f"at the {stage.lower()}"
        text = {
            "joker": f"JOKER: an extra card is turned up {when}, set apart from the board. "
                     "Every private card of that rank is wild — it can be any card.",
            "poison": f"POISON: an extra card is turned up {when}, set apart from the board. "
                      "Private cards of that rank are poisoned and can't be used.",
            "jumping": f"JUMPING JOKER: an extra card is turned up {when}. Private cards of "
                       "that rank are poison (can't be used); private cards one rank above "
                       "or below are wild (A sits next to both K and 2).",
        }[kind]
        if scope == "all":
            text = text.replace("Every private card", "Every card (private AND community)") \
                       .replace("Private cards", "All cards (private and community)") \
                       .replace("private cards", "all cards")
        return replace(self, board_groups=self.board_groups + (group,), stages=stages,
                       special=(kind, stage, scope), summary=self.summary + (text,))

    def explain(self, hand) -> HandExplanation:
        if hasattr(hand, "tp_label"):                     # Teen Patti hand
            return HandExplanation(label=hand.tp_label, cards=tuple(hand.cards))
        if hasattr(hand, "total"):                        # Blackjack Hold'em 21 row
            return HandExplanation(label="Blackjack 21" if hand.total == 21
                                   else f"Total {hand.total}", cards=())
        if isinstance(hand, pk.EightOrBetterLowHand):     # 8-or-better low
            order = "A2345678"
            ranks = sorted((getattr(c.rank, "value", str(c.rank)) for c in hand.cards),
                           key=order.index, reverse=True)
            return HandExplanation(label="-".join(ranks) + " low", cards=tuple(hand.cards))
        label = getattr(hand.entry.label, "value", str(hand.entry.label))
        # A-K-Q-J-10 of one suit gets its proper, rarer name
        if label == "Straight flush" and {getattr(c.rank, "value", str(c.rank)) for c in hand.cards} \
                == {"A", "K", "Q", "J", "T"}:
            label = "Royal flush"
        return HandExplanation(label=label, cards=tuple(hand.cards))

    def describe(self) -> dict:
        """JSON-ready description for the browser (no cards)."""
        return {
            "id": self.id, "name": self.name, "summary": list(self.summary),
            "options": dict(self.options), "scoring": self.scoring,
            "selection": self.selection, "split_hole_cards": self.split_hole_cards,
            "hole_cards": self.hole_card_count,
            "special": ({"kind": self.special[0], "stage": self.special[1],
                         "scope": self.special_scope,
                         "label": SPECIAL_KINDS[self.special[0]]} if self.special else None),
            "passing": list(self.passing), "pass_mode": self.pass_mode,
            "pass_count": self.pass_count, "dice": self.dice, "red_river": self.red_river,
            "blackjack": self.blackjack, "market": list(self.market),
            "wild_rule": self.wild_rule, "auction": self.auction,
            "wild_label": self.WILD_TEXT[self.wild_rule][0] if self.wild_rule else "",
            "board_groups": [{"id": g.id, "label": g.label, "size": g.size, "row": g.row,
                              "col": g.col, "row_span": g.row_span, "hidden": g.hidden,
                              "optional": g.optional} for g in self.board_groups],
            "rows": [{"id": r.id, "label": r.label, "groups": list(r.groups),
                      "hole_use": list(r.hole_use), "hole_alloc": r.hole_alloc,
                      "one_per_group": r.one_per_group, "kind": r.kind,
                      "jokers": r.jokers} for r in self.rows],
        }
