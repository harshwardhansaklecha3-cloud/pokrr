"""One hand of poker, run on a PokerKit ``State``.

Responsibilities split:
- PokerKit: blinds, action order, legal bet sizes, all-ins, side pots, and
  dividing each pot between winners (incl. ties, odd chips, and splitting a
  pot into equal "portions" — one per row for split-pot variations).
- This module: supplying every card from our own ``Shoe``, the showdown
  declarations (split/pick cards), deciding hand strength per row via
  ``engine.evaluate``, a public action history, and a plain result summary.

How our row rules reach PokerKit: each hand creates its own small Hand
classes, one per pot portion. When PokerKit asks "how strong is this
player's hand for portion k?", the class looks up the hand we computed from
that player's declaration.

Player numbering: PokerKit index 0 is the first seat left of the button and
the last index is the button. ``seat_ids[i]`` maps PokerKit index i -> seat.
"""
from __future__ import annotations

import itertools
import secrets
import warnings
from contextlib import contextmanager
from dataclasses import dataclass

import pokerkit as pk
from pokerkit import Automation as A

from . import evaluate as ev
from .cards import Shoe, card_str
from .variants import Variant

AUTOMATIONS = (
    A.ANTE_POSTING,
    A.BET_COLLECTION,
    A.BLIND_OR_STRADDLE_POSTING,
    A.RUNOUT_COUNT_SELECTION,
    A.CHIPS_PULLING,
)


_RANK = "23456789TJQKA"


def _rv(c) -> int:
    """Rank value 0-12 for quick bot heuristics (a joker counts as 13)."""
    r = repr(c)[0]
    return _RANK.index(r) if r in _RANK else 13


class IllegalAction(ValueError):
    """The requested action is not allowed right now."""


@contextmanager
def _strict():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


@dataclass
class LegalActions:
    fold: bool
    check: bool
    call: int
    raise_kind: str | None
    min_to: int | None
    max_to: int | None

    def as_dict(self) -> dict:
        return {"fold": self.fold, "check": self.check, "call": self.call,
                "raise_kind": self.raise_kind, "min_to": self.min_to, "max_to": self.max_to}


# PokerKit decides "dead" hands as soon as the board is complete — before
# humans have declared their cards — but only picks pot winners when chips
# are pushed. Until our real hands are known every live player reports this
# same placeholder (so nobody is killed early); pushing is only allowed after
# the real hands are filled in (asserted in HandEngine._advance).
_PLACEHOLDER = pk.StandardHighHand("7s5c4d3h2s")


def _portion_types(lookup: dict, n: int) -> tuple:
    """n Hand classes; class k reports each player's hand for portion k."""
    types = []
    for k in range(n):
        class Portion(pk.StandardHighHand):
            @classmethod
            def from_game(cls, hole_cards, board_cards=(), _k=k):
                key = frozenset(pk.Card.clean(hole_cards))
                hands = lookup.get(key)
                if hands is None:
                    return _PLACEHOLDER
                if hands[_k] is None:
                    raise ValueError("this player has no hand in this row")
                return hands[_k]
        types.append(Portion)
    return tuple(types)


class HandEngine:
    def __init__(self, variant: Variant, seat_ids: list[int], stacks: list[int],
                 small_blind: int, big_blind: int, shoe: Shoe,
                 names: dict[int, str] | None = None, auto_seats: set[int] | None = None):
        variant.validate(len(seat_ids))
        if len(seat_ids) != len(stacks):
            raise ValueError("seat_ids and stacks differ in length")
        if any(s <= 0 for s in stacks):
            raise ValueError("every dealt-in player needs chips")
        self.variant = variant
        self.seat_ids = list(seat_ids)
        self.pk_of = {seat: i for i, seat in enumerate(seat_ids)}
        self.names = names or {s: f"Seat {s + 1}" for s in seat_ids}
        self.auto_seats = set(auto_seats or ())   # bots: engine declares for them
        self.small_blind, self.big_blind = small_blind, big_blind
        self.shoe = shoe
        self.starting_stacks = list(stacks)
        self.history: list[dict] = []
        self.shown: dict[int, list[str]] = {}
        # dealt = the cards each player holds NOW (changes with Anaconda passes);
        # pk_hole = what PokerKit dealt them (never changes; used as the key
        # when PokerKit asks for a player's hand).
        self.dealt: dict[int, list[pk.Card]] = {s: [] for s in seat_ids}
        self.pk_hole: dict[int, list[pk.Card]] = {s: [] for s in seat_ids}
        self.up_cards: set = set()                 # dealt face up (everyone sees them)
        self.fold_street: dict[int, str] = {}      # seat -> round they folded in
        self.lessons: dict[int, list[str]] = {}    # seat -> private "learn" notes
        # Anaconda passing
        self.passes_done: set[int] = set()         # stage indices already passed after
        self.pass_stage: int | None = None
        self.pass_awaiting: set[int] = set()
        self.pass_choices: dict[int, pk.Card] = {}
        # Pineapple: cards each player threw away (face down)
        self.discarded: dict[int, list] = {s: [] for s in seat_ids}
        # Dice add-on
        self.dice_rolls: list[dict] = []           # what each die did (public)
        self._swaps: dict[tuple, pk.Card] = {}     # (group id, index) -> replacement card
        self.dice_roller = None                    # tests may set: () -> 1..6
        # Red River
        self.rr_stop = False                       # a black river ended the chain
        self._phantom = 0                          # cards dealt only to finish PokerKit's streets
        self._phantom_from: int | None = None
        # players out of the hand without a PokerKit fold (Blackjack bust,
        # Wall Street fold): they can't win and check/fold automatically
        self.dead: dict[int, str] = {}
        # Blackjack Hold'em: hit/stand after the flop
        self.hit_state: str | None = None          # None | "active" | "done"
        self.hit_queue: list[int] = []
        # Wall Street: the market
        self.market: list = []
        self.market_pot = 0
        self.market_state: str | None = None
        self.buy_queue: list[int] = []
        self.bought: dict[int, list] = {s: [] for s in seat_ids}
        # Joker auction
        self.auction_state: str | None = None
        self.auction_bid = 0
        self.auction_leader: int | None = None
        self.auction_out: set[int] = set()
        self.auction_order: list[int] = []
        self.auction_turn: int | None = None
        self.pushes: list = []
        self.pots_at_showdown: list[tuple[int, list[int]]] = []
        self.street_name = variant.stages[0].name
        self.result: dict | None = None
        # showdown declarations
        self.awaiting: set[int] = set()            # humans who still must declare
        self.declarations: dict[int, dict] = {}    # seat -> {row_id: (hand, hole, board)}
        self._lookup: dict = {}                    # frozenset(hole) -> portion hands
        self._evaluated = False
        self._held_shows: list = []                # reveals withheld until all choose

        with _strict():
            self.state = pk.State(
                AUTOMATIONS, variant.deck, _portion_types(self._lookup, variant.portions),
                variant.pokerkit_streets(big_blind), variant.betting, True, 0,
                (small_blind, big_blind), 0, tuple(stacks), len(stacks))
        self._record_blinds()
        self._advance()

    # ------------------------------------------------------------ helpers
    def _seat(self, pk_index: int) -> int:
        return self.seat_ids[pk_index]

    def _name(self, seat: int) -> str:
        return self.names.get(seat, f"Seat {seat + 1}")

    def _log(self, kind: str, text: str, **data) -> None:
        self.history.append({"kind": kind, "text": text, "street": self.street_name, **data})

    def roles(self) -> dict[int, str]:
        n = len(self.seat_ids)
        btn = self.seat_ids[-1]
        if n == 2:
            return {btn: "BTN/SB", self.seat_ids[0]: "BB"}
        return {self.seat_ids[0]: "SB", self.seat_ids[1]: "BB", btn: "BTN"}

    def _record_blinds(self) -> None:
        roles = self.roles()
        order = sorted(range(len(self.seat_ids)),
                       key=lambda i: 0 if "SB" in roles.get(self._seat(i), "") else 1)
        for i in order:
            amt = self.state.bets[i]
            if amt:
                seat = self._seat(i)
                kind = "small blind" if "SB" in roles.get(seat, "") else "big blind"
                self._log("blind", f"{self._name(seat)} posts {kind} {amt}",
                          seat=seat, amount=amt, action="blind")

    def live_seats(self) -> list[int]:
        return [self._seat(i) for i, alive in enumerate(self.state.statuses) if alive]

    def board_cards(self) -> dict[str, list[pk.Card]]:
        flat = list(self.state.get_board_cards(0))
        if self._phantom:                          # Red River: not real board cards
            flat = flat[:len(flat) - self._phantom]
        out = self.variant.split_board(flat)
        for (gid, i), c in self._swaps.items():    # Dice replacements
            if i < len(out.get(gid, [])):
                out[gid][i] = c
        if "dice" in out:
            out["dice"] = []                       # the spare dice cards are never shown
        return out

    # ------------------------------------------------------------ dealing
    def _at_showdown(self) -> bool:
        st = self.state
        return (st.status and st.actor_index is None and len(self.live_seats()) >= 2
                and not (st.can_deal_hole() or st.can_burn_card() or st.can_deal_board()
                         or st.can_show_or_muck_hole_cards()))

    def _hold_reveals(self) -> bool:
        """Keep showdown cards hidden until choices/passes are finished."""
        return bool(self.variant.needs_declaration or self.variant.passing) and not self._evaluated

    def _pass_due(self) -> int | None:
        """Index of a betting round just finished that requires an Anaconda
        pass which hasn't happened yet."""
        v, st = self.variant, self.state
        if not v.passing or len(self.live_seats()) < 2:
            return None
        if st.can_deal_hole() or st.can_burn_card() or st.can_deal_board():
            if st.street_index is None:
                return None
            done = st.street_index - 1
        elif self._at_showdown() and not self._evaluated:
            done = len(v.stages) - 1
        else:
            return None
        if done >= 0 and v.stages[done].name in v.passing and done not in self.passes_done:
            return done
        return None

    def _advance(self) -> None:
        st = self.state
        with _strict():
            while st.status:
                phase = self._phase_due()           # Blackjack hits / Wall Street market
                if phase:
                    if not self._run_phase(phase):
                        return              # waiting for a person to hit/stand or buy
                    continue
                if st.actor_index is not None:
                    if self._auto_actor():
                        self._auto_act()    # out-of-hand player / Red River leftovers
                        continue
                    break                   # a real betting decision
                due = self._pass_due()
                if due is not None:
                    if not self._prepare_pass(due):
                        return              # waiting for humans to pass a card
                    continue
                if st.can_deal_hole():
                    seat = self._seat(st.hole_dealee_index)
                    card = self.shoe.draw(1)
                    st.deal_hole(card)
                    self.dealt[seat] += card
                    self.pk_hole[seat] += card
                    if self.variant.stages[st.street_index or 0].hole_up:
                        self.up_cards.add(card[0])
                        self._log("upcard", f"{self._name(seat)} gets {card_str(card[0])} face up",
                                  seat=seat, cards=[card_str(card[0])])
                elif st.can_burn_card():
                    st.burn_card(self.shoe.draw(1)[0])
                elif st.can_deal_board():
                    idx = st.street_index
                    stage = self.variant.stages[idx]
                    phantom = self._red_river_over(idx)
                    cards = self.shoe.draw(st.board_dealing_count)
                    st.deal_board(cards)
                    if phantom:                    # not a real card: hand is heading to showdown
                        self._phantom += len(cards)
                        continue
                    self.street_name = stage.name
                    if stage.reveal == ("dice",):
                        self._roll_dice(cards)
                        continue
                    self._log("board", f"{stage.name}: " + " ".join(map(card_str, cards)),
                              cards=[card_str(c) for c in cards])
                    self._red_river_note(idx, cards)
                elif st.can_show_or_muck_hole_cards():
                    op = st.show_or_muck_hole_cards(True)
                    seat = self._seat(op.player_index)
                    if self._hold_reveals():
                        # Fairness: when players choose or pass cards, nobody's
                        # cards are revealed until that is all finished.
                        self._held_shows.append(seat)
                    else:
                        self._reveal(seat)
                elif self._at_showdown() and not self._evaluated:
                    if not self._prepare_showdown():
                        return          # waiting for human declarations
                elif st.can_kill_hand():
                    self._capture_pots()
                    st.kill_hand()
                elif st.can_push_chips():
                    if len(self.live_seats()) > 1 and not self._evaluated:
                        raise RuntimeError("refusing to pay out before hands are evaluated")
                    self._capture_pots()
                    self.pushes.append(st.push_chips())
                elif st.can_no_operate():
                    st.no_operate()
                else:
                    raise RuntimeError("PokerKit state is stuck (no legal dealer step)")
            if st.status and st.street_index is not None and not (
                    self._phantom_from is not None and st.street_index >= self._phantom_from):
                self.street_name = self.variant.stages[st.street_index].name
        if not st.status and self.result is None:
            self._build_result()

    def _prepare_showdown(self) -> bool:
        """Declare for bots / automatic rows; return False while humans pick."""
        board = self.board_cards()
        live = self.live_seats()
        everyone_out = all(s in self.dead for s in live)
        for seat in live:
            if seat in self.declarations:
                continue
            if seat in self.dead and not everyone_out:
                self.declarations[seat] = {r.id: None for r in self.variant.rows}
                continue
            if seat in self.auto_seats or not self.variant.needs_declaration:
                self.declarations[seat] = ev.auto_declaration(
                    self.variant, self.dealt[seat], board)
        self.awaiting = {s for s in live if s not in self.declarations}
        if self.awaiting:
            if self.street_name != "Showdown":
                self.street_name = "Showdown"
                names = ", ".join(self._name(s) for s in sorted(self.awaiting))
                self._log("declare", f"Showdown — waiting for {names} to choose cards")
            return False
        for seat in live:
            # PokerKit asks by the cards IT dealt (pk_hole), not passed ones.
            if seat in self.dead and not everyone_out:
                # out of the hand (bust / market fold): not eligible for any part
                self._lookup[frozenset(self.pk_hole[seat])] = [None] * self.variant.portions
                continue
            self._lookup[frozenset(self.pk_hole[seat])] = ev.portion_hands(
                self.variant, self.declarations[seat])
        self._evaluated = True
        for seat in self._held_shows:              # everyone has chosen: reveal
            self._reveal(seat)
        self._held_shows = []
        return True

    def _reveal(self, seat: int) -> None:
        cards = [card_str(c) for c in self.dealt[seat]]      # what they hold now
        self.shown[seat] = cards
        self._log("show", f"{self._name(seat)} shows " + " ".join(cards), seat=seat, cards=cards)

    # ------------------------------------------------------------ automatic turns
    def _auto_actor(self) -> bool:
        """The betting actor is a player who is out (bust / market fold), or
        the street only exists to finish PokerKit's fixed list (Red River)."""
        st = self.state
        if self._phantom_from is not None and st.street_index is not None \
                and st.street_index >= self._phantom_from:
            return True
        return self._seat(st.actor_index) in self.dead

    def _auto_act(self) -> None:
        st = self.state
        seat = self._seat(st.actor_index)
        if seat in self.dead and (st.checking_or_calling_amount or 0) > 0 and st.can_fold():
            st.fold()
            self.fold_street.setdefault(seat, self.street_name)
        else:
            st.check_or_call()                  # nothing to call: just move on (no log)

    # ------------------------------------------------------------ Red River
    def _red_river_over(self, idx: int) -> bool:
        """About to deal an extra river: is the chain already over (black)?"""
        v = self.variant
        if not v.red_river or idx < len(v.stages) - v.red_river:
            return False
        if not self.rr_stop:
            real = list(self.state.get_board_cards(0))
            real = real[:len(real) - self._phantom]
            suit = getattr(real[-1].suit, "value", str(real[-1].suit)) if real else "s"
            if suit in "sc":                           # black river: the chain is over
                self.rr_stop = True
        if self.rr_stop and self._phantom_from is None:
            self._phantom_from = idx
        return self.rr_stop

    def _red_river_note(self, idx: int, cards) -> None:
        v = self.variant
        if not v.red_river or idx < len(v.stages) - v.red_river - 1:
            return
        suit = getattr(cards[-1].suit, "value", str(cards[-1].suit))
        if suit in "hd" and idx < len(v.stages) - 1:
            self._log("redriver", "RED river! Another river will come after this betting round.")
        elif suit in "sc":
            self._log("redriver", "Black river — no more rivers.")

    # ------------------------------------------------------------ Dice
    def _roll_dice(self, spare) -> None:
        """One die per group of up to 5 community cards: N replaces the Nth."""
        roll = self.dice_roller or (lambda: secrets.randbelow(6) + 1)
        board = self.board_cards()
        for j, chunk in enumerate(self.variant.dice_positions()):
            die = int(roll())
            entry = {"die": die, "chunk": j, "group": None, "index": None, "old": None, "new": None}
            where = f" (cards {j * 5 + 1}-{j * 5 + len(chunk)})" if len(self.variant.dice_positions()) > 1 else ""
            if die <= len(chunk):
                gid, i = chunk[die - 1]
                old, new = board[gid][i], spare[j]
                self._swaps[(gid, i)] = new
                entry.update(group=gid, index=i, old=card_str(old), new=card_str(new))
                self._log("dice", f"Dice{where}: rolled {die} — {card_str(old)} is replaced by "
                          f"{card_str(new)}", die=die, old=card_str(old), new=card_str(new))
            else:
                self._log("dice", f"Dice{where}: rolled {die} — no change", die=die)
            self.dice_rolls.append(entry)

    # ------------------------------------------------------------ phases
    def _phase_due(self) -> str | None:
        v, st = self.variant, self.state
        if len(self.live_seats()) < 2:
            return None
        if v.market and self.market_state != "done" and not st.can_deal_hole() \
                and st.street_index == 0:
            return "market"
        if v.blackjack and self.hit_state != "done" \
                and len(self.board_cards().get("flop", [])) == 3:
            return "hit"
        # after the flop betting, before the turn card
        if v.auction and self.auction_state != "done" and (
                (st.street_index or 0) >= 2 or self._at_showdown()):
            return "auction"
        return None

    def _run_phase(self, phase: str) -> bool:
        """Run bots' turns in the phase; False while a person must choose."""
        if phase == "hit":
            if self.hit_state is None:
                self.hit_state = "active"
                self.hit_queue = [s for s in self.seat_ids if s in self.live_seats()]
                self.street_name = "Hit or stand"
                self._log("hit", "Blackjack: each player may HIT (take a card) or STAND")
            while self.hit_queue:
                seat = self.hit_queue[0]
                if seat in self.dead:
                    self.hit_queue.pop(0)
                elif seat in self.auto_seats:
                    self._bot_hits(seat)
                else:
                    return False
            self.hit_state = "done"
            self.street_name = "Flop"
            return True
        if phase == "auction":
            return self._run_auction()
        # Wall Street market
        if self.market_state is None:
            self.market_state = "active"
            self.market = self.shoe.draw(self.variant.market[0])
            self.buy_queue = [s for s in self.seat_ids if s in self.live_seats()]
            self.street_name = "Market"
            self._log("market", "The market opens: " + ", ".join(
                f"{card_str(c)} ({self.price(c)})" for c in self.market))
        while self.buy_queue:
            seat = self.buy_queue[0]
            if seat in self.dead or len(self.bought[seat]) >= self.variant.market[1]:
                self.buy_queue.pop(0)
            elif not self._affordable(seat):
                self._log("market", f"{self._name(seat)} can't afford any card and stops buying",
                          seat=seat)
                self.buy_queue.pop(0)
            elif seat in self.auto_seats:
                self._buy(seat, self._bot_buy_choice(seat))
            else:
                return False
        self.market_state = "done"
        self.street_name = self.variant.stages[0].name
        self._log("market", "The market closes — final round of betting")
        return True

    @property
    def phase_turn(self) -> tuple[str, int] | None:
        """("hit" | "buy" | "bid", seat) while the table waits for that person."""
        if self.hit_state == "active" and self.hit_queue:
            return ("hit", self.hit_queue[0])
        if self.market_state == "active" and self.buy_queue:
            return ("buy", self.buy_queue[0])
        if self.auction_state == "active" and self.auction_turn is not None:
            return ("bid", self.auction_turn)
        return None

    # Joker auction
    def auction_min(self) -> int:
        return self.auction_bid + self.big_blind

    def _can_bid(self, seat: int) -> bool:
        return self.auction_min() < self.stack(seat)          # keep at least 1 chip

    def _next_bidder(self) -> int | None:
        """Next player (in order after the last bidder) still in the auction."""
        order = self.auction_order
        start = order.index(self.auction_turn) + 1 if self.auction_turn in order else 0
        for k in range(len(order)):
            s = order[(start + k) % len(order)]
            if s in self.auction_out or s == self.auction_leader:
                continue
            if not self._can_bid(s):
                self.auction_out.add(s)
                continue
            return s
        return None

    def _run_auction(self) -> bool:
        if self.auction_state is None:
            self.auction_state = "active"
            self.auction_order = [s for s in self.seat_ids
                                  if s in self.live_seats() and s not in self.dead]
            self.street_name = "Joker auction"
            self._log("auction", "JOKER AUCTION! Bid for a wild joker — the top bid goes into the pot")
            self.auction_turn = None
            self.auction_turn = self._next_bidder()
        while self.auction_turn is not None:
            seat = self.auction_turn
            if seat in self.auto_seats:
                amount = self._bot_bid(seat)
                if amount:
                    self._bid(seat, amount)
                else:
                    self._drop(seat)
            else:
                return False
        self._finish_auction()
        return True

    def _bid(self, seat: int, amount: int) -> None:
        self.auction_bid, self.auction_leader = amount, seat
        self._log("bid", f"{self._name(seat)} bids {amount} for the joker", seat=seat, amount=amount)
        self.auction_turn = self._next_bidder()

    def _drop(self, seat: int) -> None:
        self.auction_out.add(seat)
        self._log("bid", f"{self._name(seat)} drops out of the auction", seat=seat)
        self.auction_turn = self._next_bidder()

    def _finish_auction(self) -> None:
        self.auction_state = "done"
        self.auction_turn = None
        seat = self.auction_leader
        if seat is None:
            self._log("auction", "Nobody bid — the joker goes back in the box")
        else:
            self.state.stacks[self.pk_of[seat]] -= self.auction_bid
            self.market_pot += self.auction_bid
            self.dealt[seat].append(ev.AUCTION_JOKER)
            self.up_cards.add(ev.AUCTION_JOKER)
            self._log("auction", f"{self._name(seat)} wins the JOKER for {self.auction_bid}!",
                      seat=seat, amount=self.auction_bid, cards=[repr(ev.AUCTION_JOKER)])
        if self.state.street_index is not None:
            self.street_name = self.variant.stages[min(self.state.street_index,
                                                       len(self.variant.stages) - 1)].name

    def _bot_bid(self, seat: int) -> int:
        """Bid while the price is below what a wild card seems worth to us."""
        board = self.board_cards()
        res = ev.auto_declaration(self.variant, self.dealt[seat], board)
        now = max((ev.strength(r[0]) for r in res.values() if r), default=0.0)
        boosted = ev.auto_declaration(self.variant, self.dealt[seat] + [ev.AUCTION_JOKER], board)
        later = max((ev.strength(r[0]) for r in boosted.values() if r), default=0.0)
        worth = self.big_blind * (2 + 25 * max(0.0, later - now) + 4 * later)
        worth *= secrets.SystemRandom().uniform(0.7, 1.3)
        price = self.auction_min()
        return price if price <= worth and price < self.stack(seat) else 0

    def bid(self, seat: int, amount: int) -> None:
        if self.phase_turn != ("bid", seat):
            raise IllegalAction("it's not your turn to bid")
        if not isinstance(amount, int) or amount < self.auction_min():
            raise IllegalAction(f"bid at least {self.auction_min()}")
        if amount >= self.stack(seat):
            raise IllegalAction("you can't bid all your chips (keep at least 1)")
        self._bid(seat, amount)
        self._advance()

    def drop(self, seat: int) -> None:
        if self.phase_turn != ("bid", seat):
            raise IllegalAction("it's not your turn")
        self._drop(seat)
        self._advance()

    # Blackjack Hold'em
    def hit(self, seat: int) -> None:
        if self.phase_turn != ("hit", seat):
            raise IllegalAction("it's not your turn to hit or stand")
        self._hit(seat)
        self._advance()

    def stand(self, seat: int) -> None:
        if self.phase_turn != ("hit", seat):
            raise IllegalAction("it's not your turn to hit or stand")
        self.hit_queue.pop(0)
        self._log("hit", f"{self._name(seat)} stands with {len(self.dealt[seat])} cards", seat=seat)
        self._advance()

    def _hit(self, seat: int) -> None:
        card = self.shoe.draw(1)
        self.dealt[seat] += card
        total = ev.bj_total(self.dealt[seat])
        if total > 21:
            self.dead[seat] = "bust"
            self.hit_queue.pop(0)
            self._log("bust", f"{self._name(seat)} hits and BUSTS — out of the hand", seat=seat)
        else:
            self._log("hit", f"{self._name(seat)} hits ({len(self.dealt[seat])} cards)", seat=seat)
            if total == 21:
                self.hit_queue.pop(0)

    def _bot_hits(self, seat: int) -> None:
        rng = secrets.SystemRandom()
        while self.hit_queue and self.hit_queue[0] == seat:
            total = ev.bj_total(self.dealt[seat])
            if total <= 11 or (total <= 16 and rng.random() < (17 - total) / 8):
                self._hit(seat)
            else:
                self.hit_queue.pop(0)
                self._log("hit", f"{self._name(seat)} stands with {len(self.dealt[seat])} cards",
                          seat=seat)

    # Wall Street
    def price(self, card) -> int:
        r = getattr(card.rank, "value", str(card.rank))
        return self.big_blind * (3 if r == "A" else 2 if r in "TJQK" else 1)

    def _affordable(self, seat: int) -> bool:
        stack = self.stack(seat)
        return any(self.price(c) < stack for c in self.market)

    def buy(self, seat: int, code: str) -> None:
        if self.phase_turn != ("buy", seat):
            raise IllegalAction("it's not your turn to buy")
        card = next((c for c in self.market if card_str(c) == code), None)
        if card is None:
            raise IllegalAction("that card isn't in the market")
        if self.price(card) >= self.stack(seat):
            raise IllegalAction("you can't afford that card (keep at least 1 chip)")
        self._buy(seat, card)
        self._advance()

    def market_fold(self, seat: int) -> None:
        if self.phase_turn != ("buy", seat):
            raise IllegalAction("it's not your turn")
        self.dead[seat] = "folded"
        self.fold_street[seat] = "Market"
        self.buy_queue.pop(0)
        self._log("action", f"{self._name(seat)} folds", seat=seat, action="fold")
        self._advance()

    def _buy(self, seat: int, card) -> None:
        price = self.price(card)
        self.state.stacks[self.pk_of[seat]] -= price
        self.market_pot += price
        i = self.market.index(card)
        self.market[i] = self.shoe.draw(1)[0]          # the market is refilled at once
        self.bought[seat].append(card)
        self.dealt[seat].append(card)
        self.up_cards.add(card)
        self._log("buy", f"{self._name(seat)} buys {card_str(card)} for {price}", seat=seat,
                  cards=[card_str(card)], amount=price)
        self.buy_queue.pop(0)
        if len(self.bought[seat]) < self.variant.market[1]:
            self.buy_queue.append(seat)                   # round-robin: one card per turn

    def _bot_buy_choice(self, seat: int):
        """The card that helps most (by a quick look at pairs, suits and runs)."""
        stack = self.stack(seat)
        options = [c for c in self.market if self.price(c) < stack]
        own = self.dealt[seat]

        def value(c):
            cards = own + [c]
            if len(cards) >= 5:
                row = self.variant.rows[0]
                res = ev.best_for_row(row, cards, {})
                return 10 * ev.strength(res[0]) if res else 0
            ranks = [_rv(x) for x in cards]
            suits = [repr(x)[1] for x in cards]
            pairs = sum(ranks.count(r) - 1 for r in set(ranks))
            flush = max(suits.count(s) for s in set(suits))
            run = len({r for r in ranks if abs(r - _rv(c)) <= 2})
            return pairs * 3 + flush + run * 0.5 + _rv(c) / 12
        return max(options, key=lambda c: (value(c), -self.price(c)))

    def time_out_phase(self, seat: int) -> str:
        """A person ran out of time in a phase: stand / buy a sensible card."""
        turn = self.phase_turn
        if turn == ("hit", seat):
            self.stand(seat)
            return "stand"
        if turn == ("buy", seat):
            self._buy(seat, self._bot_buy_choice(seat))
            self._advance()
            return "buy"
        if turn == ("bid", seat):
            self.drop(seat)
            return "drop"
        raise IllegalAction("nothing to do for that seat")

    # ------------------------------------------------------------ Anaconda
    def _judge(self, seat: int, rest: list) -> float:
        """How good the cards ``rest`` are for this seat right now (bots)."""
        board = self.board_cards()
        if sum(len(x) for x in board.values()) < 3:          # no board yet: rough preflop value
            ranks = sorted((_rv(c) for c in rest), reverse=True)
            suits = [repr(c)[1] for c in rest]
            pairs = sum(ranks.count(r) - 1 for r in set(ranks))
            suited = max(suits.count(s) for s in set(suits)) if suits else 0
            runs = sum(1 for a, b in zip(ranks, ranks[1:]) if 0 < a - b <= 2)
            return pairs * 20 + sum(ranks[:2]) + suited * 2 + runs * 2
        # Judge with the split rule relaxed: with cards gone, the cards may not
        # split evenly, but "how good is what's left" still works.
        from dataclasses import replace
        judge = replace(self.variant, rows=tuple(replace(r, hole_alloc=None)
                                                 for r in self.variant.rows))
        res = ev.auto_declaration(judge, rest, board)
        vals = [ev.strength(r[0]) if r else -1.0 for r in res.values()]
        return max(vals) if vals else -1.0

    def _bot_pass_choice(self, seat: int):
        """Anaconda: the card whose loss hurts the least. Pineapple: the card(s)
        to throw away, chosen the same way."""
        hole = [c for c in self.dealt[seat] if c not in self.up_cards]
        n = self.variant.pass_count if self.variant.pass_mode == "discard" else 1
        best, best_val = list(hole[:n]), None
        for combo in itertools.combinations(hole, n):
            rest = [x for x in self.dealt[seat] if x not in combo]
            val = self._judge(seat, rest)
            if best_val is None or val > best_val:
                best, best_val = list(combo), val
        return best if self.variant.pass_mode == "discard" else best[0]

    def _pass_complete(self, seat: int) -> bool:
        if self.variant.pass_mode == "discard":
            return len(self.pass_choices.get(seat, [])) >= self.variant.pass_count
        return seat in self.pass_choices

    def _prepare_pass(self, stage_index: int) -> bool:
        """Collect the cards from every live player; False while humans choose."""
        live = [s for s in self.live_seats() if s not in self.dead]
        discard = self.variant.pass_mode == "discard"
        n = self.variant.pass_count
        if self.pass_stage != stage_index:
            self.pass_stage = stage_index
            self.pass_choices = {}
            self.street_name = "Throw away" if discard else "Pass"
            self._log("pass", (f"Pineapple — everyone throws away {n} card{'s' if n > 1 else ''}"
                               if discard else
                               "Anaconda — everyone passes 1 card to the player on their left"))
        for seat in live:
            if not self._pass_complete(seat) and seat in self.auto_seats:
                self.pass_choices[seat] = self._bot_pass_choice(seat)
        self.pass_awaiting = {s for s in live if not self._pass_complete(s)}
        if self.pass_awaiting:
            return False
        order = [s for s in self.seat_ids if s in live]
        if discard:
            for s in order:
                gone = self.pass_choices[s]
                self.dealt[s] = [c for c in self.dealt[s] if c not in gone]
                self.discarded[s] += gone
                self._log("discard", f"{self._name(s)} throws away {len(gone)} "
                          f"card{'s' if len(gone) > 1 else ''}", seat=s)
        else:
            # Everyone has chosen: pass simultaneously to the next live player on
            # the left (clockwise = next in PokerKit order, which starts left of
            # the button).
            given = {s: self.pass_choices[s] for s in order}
            for s in order:
                self.dealt[s] = [c for c in self.dealt[s] if c is not given[s] and c != given[s]]
            for i, s in enumerate(order):
                to = order[(i + 1) % len(order)]
                self.dealt[to].append(given[s])
                self._log("pass", f"{self._name(s)} passes a card to {self._name(to)}",
                          seat=s, to=to)
        self.passes_done.add(stage_index)
        self.pass_stage, self.pass_choices, self.pass_awaiting = None, {}, set()
        return True

    def pass_card(self, seat: int, code: str) -> None:
        if seat not in self.pass_awaiting:
            raise IllegalAction("you have no card to pass right now")
        try:
            card = ev.parse_one(code)
        except (ValueError, StopIteration, TypeError):
            raise IllegalAction("unreadable card") from None
        mine = [c for c in self.dealt[seat] if c not in self.up_cards]
        if card not in mine:
            raise IllegalAction("you can only use one of your own face-down cards")
        if self.variant.pass_mode == "discard":
            chosen = self.pass_choices.setdefault(seat, [])
            if card in chosen:
                raise IllegalAction("you already chose that card")
            chosen.append(card)
        else:
            self.pass_choices[seat] = card
        if self._pass_complete(seat):
            self.pass_awaiting.discard(seat)
            self._advance()

    def auto_pass(self, seat: int) -> None:
        """Time ran out (or the player left): pass / throw away what a bot would."""
        if seat not in self.pass_awaiting:
            raise IllegalAction("you have no card to pass right now")
        self.pass_choices[seat] = self._bot_pass_choice(seat)
        self.pass_awaiting.discard(seat)
        verb = "thrown away" if self.variant.pass_mode == "discard" else "passed"
        self._log("pass", f"{self._name(seat)} ran out of time — cards were {verb} for them",
                  seat=seat)
        self._advance()

    def auto_declare(self, seat: int) -> None:
        """Time ran out (or the player left): use the best possible choice."""
        if seat not in self.awaiting:
            raise IllegalAction("you have nothing to declare right now")
        self.declarations[seat] = ev.auto_declaration(self.variant, self.dealt[seat],
                                                      self.board_cards())
        self.awaiting.discard(seat)
        self._log("declare", f"{self._name(seat)} ran out of time — best cards chosen for them",
                  seat=seat)
        self._advance()

    def declare(self, seat: int, decl: dict) -> None:
        if seat not in self.awaiting:
            raise IllegalAction("you have nothing to declare right now")
        try:
            result = ev.apply_declaration(self.variant, self.dealt[seat],
                                          self.board_cards(), decl)
        except ev.DeclarationError as e:
            raise IllegalAction(str(e)) from None
        self.declarations[seat] = result
        self.awaiting.discard(seat)
        self._log("declare", f"{self._name(seat)} has chosen their cards", seat=seat)
        self._advance()

    def _capture_pots(self) -> None:
        if not self.pots_at_showdown:
            self.pots_at_showdown = [
                (p.amount, [self._seat(i) for i in p.player_indices]) for p in self.state.pots]

    # ------------------------------------------------------------ queries
    @property
    def finished(self) -> bool:
        return not self.state.status

    @property
    def actor_seat(self) -> int | None:
        i = self.state.actor_index
        if i is None or self.phase_turn is not None or self.pass_awaiting or self.awaiting:
            return None                    # hitting / buying / passing comes first
        return self._seat(i)

    def hole_cards(self, seat: int) -> list[str]:
        return [card_str(c) for c in self.dealt[seat]]

    def public_cards(self, seat: int) -> list | None:
        """What OTHER players may see of this seat's cards: face-up cards as
        codes, face-down ones as None. None if nothing is face up."""
        cards = self.dealt[seat]
        if not any(c in self.up_cards for c in cards):
            return None
        return [card_str(c) if c in self.up_cards else None for c in cards]

    def board(self) -> dict[str, list[str]]:
        return {gid: [card_str(c) for c in cards] for gid, cards in self.board_cards().items()}

    def stack(self, seat: int) -> int:
        return self.state.stacks[self.pk_of[seat]]

    def bet(self, seat: int) -> int:
        return self.state.bets[self.pk_of[seat]]

    def folded(self, seat: int) -> bool:
        return seat not in self.shown and not self.state.statuses[self.pk_of[seat]]

    def pots(self) -> list[dict]:
        src = self.pots_at_showdown if self.finished else [
            (p.amount, [self._seat(i) for i in p.player_indices]) for p in self.state.pots]
        out = [{"amount": a, "eligible": e} for a, e in src]
        if self.market_pot and not self.finished:      # Wall Street purchases join the main pot
            if out:
                out[0]["amount"] += self.market_pot
            else:
                out = [{"amount": self.market_pot, "eligible": self.live_seats()}]
        return out

    def total_pot(self) -> int:
        if self.finished:
            return sum(a for a, _ in self.pots_at_showdown)
        return sum(p.amount for p in self.state.pots) + sum(self.state.bets) + self.market_pot

    def legal_actions(self, seat: int) -> LegalActions | None:
        if self.finished or self.actor_seat != seat:
            return None
        st = self.state
        with _strict():
            can_raise = st.can_complete_bet_or_raise_to()
            call_amt = st.checking_or_calling_amount or 0
            return LegalActions(
                fold=st.can_fold(),
                check=st.can_check_or_call() and call_amt == 0,
                call=call_amt if st.can_check_or_call() else 0,
                raise_kind=("bet" if self._is_bet() else "raise") if can_raise else None,
                min_to=st.min_completion_betting_or_raising_to_amount if can_raise else None,
                max_to=st.max_completion_betting_or_raising_to_amount if can_raise else None,
            )

    def nuts(self) -> list[dict]:
        """Best and second-best possible hands on the current board (public
        information only; worked out once per new board card)."""
        board = self.board_cards()
        key = (tuple(len(board.get(g.id, [])) for g in self.variant.board_groups),
               len(self._swaps))
        cache = self.__dict__.setdefault("_nuts_cache", {})
        if key not in cache:
            from .nuts import top_two
            try:
                cache[key] = top_two(self.variant, board)
            except Exception:                 # a learning extra: never break a hand
                cache[key] = []
        return cache[key]

    def current_hand_labels(self, seat: int) -> list[dict]:
        """The viewer's best hand per row so far (only for shared-card rows,
        where there is no assignment choice to give away)."""
        if self.variant.split_hole_cards or self.folded(seat):
            return []
        board = self.board_cards()
        hole = ev.prepare(self.variant, self.dealt[seat], board)
        pboard = ev.prepare_board(self.variant, board)
        out, best = [], None
        for r in self.variant.rows:
            res = ev.best_for_row(r, hole, pboard)
            if res:
                wild = any(isinstance(c, ev.Wild) for c in tuple(res[1]) + tuple(res[2]))
                item = {"row": r.label, "label": self.variant.explain(res[0]).label
                        + (" (joker)" if wild else "")}
                out.append(item)
                if best is None or ev.strength(res[0]) > best[0]:
                    best = (ev.strength(res[0]), item)
        if self.variant.scoring == "best" and len(out) > 1:
            return [best[1]]                 # best-row games: just your best row
        if self.variant.blackjack:
            total = ev.bj_total(self.dealt[seat])
            out.append({"row": "21", "label": "BUST" if total > 21 else
                        ("Blackjack 21" if total == 21 else f"Total {total}")})
        return out

    # ------------------------------------------------------------ actions
    def act(self, seat: int, kind: str, amount: int | None = None) -> None:
        legal = self.legal_actions(seat)
        if legal is None:
            raise IllegalAction("it is not your turn")
        st = self.state
        name = self._name(seat)
        i = self.pk_of[seat]
        try:
            with _strict():
                if kind == "fold":
                    if not legal.fold:
                        raise IllegalAction("folding is not allowed (you can check)")
                    st.fold()
                    self.fold_street[seat] = self.street_name
                    self._log("action", f"{name} folds", seat=seat, action="fold")
                elif kind == "check":
                    if not legal.check:
                        raise IllegalAction("you cannot check; there is a bet to call")
                    st.check_or_call()
                    self._log("action", f"{name} checks", seat=seat, action="check")
                elif kind == "call":
                    if legal.call <= 0:
                        raise IllegalAction("there is nothing to call")
                    st.check_or_call()
                    allin = st.stacks[i] == 0
                    self._log("action", f"{name} calls {legal.call}" + (" (all-in)" if allin else ""),
                              seat=seat, action="call", amount=legal.call, all_in=allin)
                elif kind in ("bet", "raise"):
                    if legal.raise_kind is None:
                        raise IllegalAction("betting/raising is not allowed now")
                    if not isinstance(amount, int) or isinstance(amount, bool):
                        raise IllegalAction("bet amount must be a whole number")
                    if not legal.min_to <= amount <= legal.max_to:
                        raise IllegalAction(
                            f"amount must be between {legal.min_to} and {legal.max_to}")
                    is_bet = self._is_bet()
                    st.complete_bet_or_raise_to(amount)
                    allin = st.stacks[i] == 0
                    self._log("action", f"{name} {'bets' if is_bet else 'raises to'} {amount}"
                              + (" (all-in)" if allin else ""), seat=seat,
                              action="bet" if is_bet else "raise", amount=amount, all_in=allin)
                else:
                    raise IllegalAction(f"unknown action {kind!r}")
        except ValueError as e:
            if isinstance(e, IllegalAction):
                raise
            raise IllegalAction(str(e)) from e
        self._advance()

    def _is_bet(self) -> bool:
        st = self.state
        return st.street_index != 0 and max(st.bets) == 0

    # ------------------------------------------------------------ results
    def _pay_market(self) -> None:
        """Wall Street: the money paid for investment cards goes to whoever
        wins the main pot (shared equally on a tie)."""
        if not self.market_pot:
            return
        won: dict[int, int] = {}
        for push in self.pushes:
            if push.pot_index == 0:
                for i, a in enumerate(push.amounts):
                    if a > 0:
                        won[i] = won.get(i, 0) + a
        winners = sorted(won) or [i for i, alive in enumerate(self.state.statuses) if alive][:1]
        share, odd = divmod(self.market_pot, len(winners))
        for k, i in enumerate(winners):
            self.state.stacks[i] += share + (odd if k == 0 else 0)
        self.market_won = {self._seat(i): share + (odd if k == 0 else 0)
                           for k, i in enumerate(winners)}
        if self.pots_at_showdown:
            a, e = self.pots_at_showdown[0]
            self.pots_at_showdown[0] = (a + self.market_pot, e)
        self.market_pot = 0

    def _build_result(self) -> None:
        self._pay_market()
        st = self.state
        v = self.variant
        showdown = self._evaluated
        hands = {}
        if showdown:
            for seat, rows in self.declarations.items():
                rlist = []
                for r in v.rows:
                    res = rows.get(r.id)
                    if res is None:          # e.g. poison left no legal hand
                        rlist.append({"row": r.id, "row_label": r.label,
                                      "label": "No legal hand", "cards": [], "hole_used": [],
                                      "jokers": []})
                        continue
                    hand, h, b = res
                    if r.kind == "bj21":             # Blackjack Hold'em: the 21 total
                        codes = [card_str(c) for c in h]
                        rlist.append({"row": r.id, "row_label": r.label, "kind": r.kind,
                                      "label": v.explain(hand).label, "cards": codes,
                                      "played": [{"code": c, "joker": None} for c in codes],
                                      "hole_used": codes, "jokers": [], "joker_text": ""})
                        continue
                    used = tuple(h) + tuple(b)
                    uses = ev.joker_uses(hand, used)          # [(wild card, plays as)]
                    free = [card_str(p) for w, p in uses if w is None]   # row jokers
                    uses = [(w, p) for w, p in uses if w is not None]
                    used = tuple(c for c in used if not isinstance(c, ev.RowJoker))
                    jokers = [card_str(w) for w, _ in uses]
                    as_map = {card_str(w): card_str(p) for w, p in uses}
                    # the hand exactly as it plays: jokers replaced, marked
                    played = [{"code": as_map.get(card_str(c), card_str(c)),
                              "joker": card_str(c) if card_str(c) in as_map else None}
                              for c in used] + [{"code": p, "joker": "🃏"} for p in free]
                    jtext = [f"{w} plays as {p}" for w, p in as_map.items()] + \
                        [f"free joker plays as {p}" for p in free]
                    rlist.append({"row": r.id, "row_label": r.label, "kind": r.kind,
                                  "label": v.explain(hand).label
                                  + (" (joker)" if jokers or free else ""),
                                  "cards": [card_str(c) for c in used],
                                  "played": played,
                                  "hole_used": [card_str(c) for c in h], "jokers": jokers,
                                  "joker_text": ", ".join(jtext)})
                if v.scoring == "best" and v.selection == "declare" and len(v.rows) > 1:
                    # one-row claims: show only the row that counts
                    claimed = [x for x in rlist if x["cards"]]
                    rlist = ([max(claimed, key=lambda x: ev.strength(rows[x["row"]][0]))]
                             if claimed else rlist[:1])
                best = max((x for x in rlist if x["cards"]),
                           key=lambda x: ev.strength(rows[x["row"]][0]), default=None)
                hands[seat] = {"rows": rlist,
                               "label": best["label"] if best else "No legal hand",
                               "cards": best["cards"] if best else []}
        pots = []
        for push in self.pushes:
            amount, eligible = self.pots_at_showdown[push.pot_index]
            winners = [{"seat": self._seat(i), "amount": a}
                       for i, a in enumerate(push.amounts) if a > 0]
            portion = push.hand_type_index
            row = v.rows[portion] if (portion is not None and v.scoring == "split"
                                      and v.portions > 1) else None
            pots.append({"index": push.pot_index,
                         "name": "Main pot" if push.pot_index == 0 else f"Side pot {push.pot_index}",
                         "row": row.id if row else None, "row_label": row.label if row else None,
                         "amount": sum(push.amounts), "pot_amount": amount,
                         "eligible": eligible, "winners": winners})
        market_won = getattr(self, "market_won", {})
        if market_won:                       # Wall Street purchases, won with the main pot
            first = next((p for p in pots if p["index"] == 0), None)
            if first:
                for w in first["winners"]:
                    w["amount"] += market_won.get(w["seat"], 0)
                first["amount"] += sum(market_won.values())
        net = {seat: st.stacks[i] - self.starting_stacks[i] for i, seat in enumerate(self.seat_ids)}
        lines = []
        if not showdown and pots:
            lines = [f"{self._name(pots[0]['winners'][0]['seat'])} wins "
                     f"{sum(p['amount'] for p in pots)} — everyone else folded"]
        else:
            for p in pots:
                ws = p["winners"]
                names = " and ".join(self._name(w["seat"]) for w in ws)
                part = f" ({p['row_label']})" if p["row_label"] else (
                    " — every row" if v.portions > 1 else "")
                how = ""
                if ws and ws[0]["seat"] in hands:
                    hd = hands[ws[0]["seat"]]
                    rd = next((x for x in hd["rows"] if x["row"] == p["row"]), None)
                    lab, cards = (rd["label"], rd["cards"]) if rd else (hd["label"], hd["cards"])
                    how = f" with {lab} ({' '.join(cards)})"
                lines.append(f"{names} win{'s' if len(ws) == 1 else ''} "
                             f"{p['name'].lower()}{part}: {p['amount']}"
                             f"{' (split)' if len(ws) > 1 else ''}{how}")
        for line in lines:
            self._log("result", line)
        self.result = {"showdown": showdown, "hands": hands, "pots": pots,
                       "net": net, "summary": lines}
        try:
            self._build_lessons(pots)
        except Exception:            # lessons are a teaching extra: never break a hand
            self.lessons = {}

    # ------------------------------------------------------------ lessons
    def _hand_label(self, hand) -> str:
        if hand is ev.NO_HAND or hand is ev.TP_NO_HAND:
            return "no legal hand"
        return self.variant.explain(hand).label

    @staticmethod
    def _cards_text(res) -> str:
        if not res:
            return ""
        return " ".join(card_str(c) for c in tuple(res[1]) + tuple(res[2]))

    def _why(self, theirs, mine) -> str:
        t, m = self._hand_label(theirs), self._hand_label(mine)
        if t != m:
            return f"{t} ranks above {m}."
        return f"both were {t} — theirs had the higher cards."

    def _build_lessons(self, pots) -> None:
        """Private notes for each human: how they won or lost each part of
        the pot, a better showdown choice if one existed, and what folding
        cost (or saved). Uses only that player's own cards + public info."""
        v = self.variant
        board = self.board_cards()
        complete = all(len(board.get(g.id, [])) == g.size for g in v.board_groups)
        showdown = self._evaluated
        parts = ([r.label.split(" (")[0] for r in v.rows]
                 if v.scoring == "split" and len(v.rows) > 1 else ["the pot"])
        others_p = {s: ev.portion_hands(v, d) for s, d in self.declarations.items()}

        def top_other(k, me):
            vals = [(p[k], s) for s, p in others_p.items() if s != me]
            return max(vals, key=lambda x: x[0]) if vals else (None, None)

        def row_for(k, decl):
            if v.scoring == "split":
                return decl.get(v.rows[k].id)
            live = [x for x in decl.values() if x]
            return max(live, key=lambda x: ev.strength(x[0])) if live else None

        for seat in self.seat_ids:
            if seat in self.auto_seats:
                continue
            L: list[str] = []
            if seat in self.fold_street:
                L.append(f"You folded on the {self.fold_street[seat].lower()} holding "
                         f"{' '.join(self.hole_cards(seat))}.")
                if complete:
                    mine = ev.auto_declaration(v, self.dealt[seat], board)
                    my_p = ev.portion_hands(v, mine)
                    best = max(my_p, key=ev.strength)
                    L.append(f"With the full board your best would have been {self._hand_label(best)}.")
                    if showdown:
                        for k, h in enumerate(my_p):
                            top, who = top_other(k, seat)
                            if top is None:
                                continue
                            where = f" ({parts[k]})" if len(parts) > 1 else ""
                            if h > top:
                                L.append(f"That would have WON{where} against {self._name(who)}'s "
                                         f"{self._hand_label(top)} — folding cost you here.")
                            elif h == top:
                                L.append(f"That would have tied{where} with {self._name(who)}.")
                            else:
                                L.append(f"It would still have lost{where} to {self._name(who)}'s "
                                         f"{self._hand_label(top)} — good fold, it saved you chips.")
            elif showdown and seat in self.declarations:
                mine = self.declarations[seat]
                my_p = others_p[seat]
                for k, h in enumerate(my_p):
                    top, who = top_other(k, seat)
                    where = parts[k]
                    if top is None:
                        continue
                    if h >= top:
                        L.append(f"You {'won' if h > top else 'tied'} {where} with "
                                 f"{self._hand_label(h)}; the next best was {self._name(who)}'s "
                                 f"{self._hand_label(top)}.")
                    else:
                        L.append(f"{self._name(who)}'s {self._hand_label(top)} "
                                 f"({self._cards_text(row_for(k, self.declarations[who]))}) beat your "
                                 f"{self._hand_label(h)} in {where}: {self._why(top, h)}")
                if v.needs_declaration:
                    best = ev.auto_declaration(v, self.dealt[seat], board)
                    best_p = ev.portion_hands(v, best)
                    for k, (b, h) in enumerate(zip(best_p, my_p)):
                        if b > h:
                            top, who = top_other(k, seat)
                            res = row_for(k, best)
                            wins = top is not None and b > top
                            L.append(f"Better choice for {parts[k]}: {self._hand_label(b)} using "
                                     f"{self._cards_text(res)}" + (" — that would have WON it!" if wins else "."))
            elif not showdown:
                won = any(w["seat"] == seat for p in pots for w in p["winners"])
                if won:
                    L.append("Everyone else folded — you won without having to show your cards.")
            if L:
                self.lessons[seat] = L
