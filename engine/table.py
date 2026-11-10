"""A poker table: seats, chips, the dealer button, and a sequence of hands.

The table is the single authority. Clients (browsers, bots) get a filtered
*view* and send *action requests*; every request is checked here.
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field, replace

from .cards import Shoe
from .hand import HandEngine, IllegalAction
from .variants import Variant, VariantError, build_variant, catalogue


BOUNTY_BB = 5                            # 7-2 bounty: each other player pays 5 big blinds


def _flag(v) -> bool:
    return v is True or v in ("on", "true", "1", 1)


@dataclass(frozen=True)
class TableSettings:
    starting_stack: int = 500
    small_blind: int = 10
    big_blind: int = 10
    variant_id: str = "classic"
    variant_options: tuple = ()          # sorted (key, value) pairs
    special_kind: str = "none"           # none | joker | poison | jumping
    special_stage: str = "River"         # Flop | Turn | River
    special_scope: str = "private"       # private | all (community cards too)
    anaconda: str = "off"                # off | flop | every
    claim: bool = False                  # players claim their own hand (the app: on)
    pineapple: str = "off"               # off | preflop | flop | every (throw cards away)
    pine_count: int = 1                  # cards thrown away each time (Irish = 2)
    dice: bool = False                   # Dice add-on
    bounty: bool = False                 # 7-2 bounty add-on
    wild: str = "off"                    # off | deuces | oneeyed | jokers | queen | river
    auction: bool = False                # Joker auction add-on
    deck: str = "standard"               # standard | short (6-A) | royal (10-A)

    def validate(self) -> None:
        if not all(isinstance(x, int) and not isinstance(x, bool)
                   for x in (self.small_blind, self.big_blind, self.starting_stack)):
            raise ValueError("chip amounts must be whole numbers")
        if not 0 < self.small_blind <= self.big_blind:
            raise ValueError("need 0 < small blind <= big blind")
        if self.starting_stack < self.big_blind:
            raise ValueError("starting stack must be at least one big blind")
        self.variant()

    def variant(self) -> Variant:
        v = build_variant(self.variant_id, dict(self.variant_options))
        v = v.with_deck(self.deck)
        check_combo(self, v)
        if self.special_kind != "none":
            v = v.with_special(self.special_kind, self.special_stage, self.special_scope)
        if self.wild != "off":
            v = v.with_wild_rule(self.wild)
        if self.anaconda != "off":
            v = v.with_passing(self.anaconda)
        if self.pineapple != "off":
            v = v.with_pineapple(self.pineapple, self.pine_count)
        if self.dice:
            v = v.with_dice()
        if self.auction:
            v = v.with_auction()
        if self.bounty:
            v = replace(v, summary=v.summary + (
                f"7-2 BOUNTY: win a pot holding a 7 and a 2 in your private cards and every "
                f"other player pays you {BOUNTY_BB} big blinds.",))
        if self.claim:
            v = v.with_claims()
        v.validate()
        return v

    def as_dict(self) -> dict:
        return {"small_blind": self.small_blind, "big_blind": self.big_blind,
                "starting_stack": self.starting_stack, "variant_id": self.variant_id,
                "variant_options": dict(self.variant_options),
                "special_kind": self.special_kind, "special_stage": self.special_stage,
                "special_scope": self.special_scope, "anaconda": self.anaconda,
                "claim": self.claim, "pineapple": self.pineapple, "pine_count": self.pine_count,
                "dice": self.dice, "bounty": self.bounty, "wild": self.wild,
                "auction": self.auction, "deck": self.deck}

    def with_choice(self, sel: dict) -> "TableSettings":
        """These settings with a dealer's choice applied (from the browser)."""
        opts = sel.get("options") or {}
        if not isinstance(opts, dict):
            raise ValueError("options must be an object")
        return TableSettings(
            self.starting_stack,
            int(sel.get("small_blind", self.small_blind)), int(sel.get("big_blind", self.big_blind)),
            str(sel.get("variant_id", self.variant_id)),
            tuple(sorted((str(k), str(v)) for k, v in opts.items())),
            str(sel.get("special_kind", "none")), str(sel.get("special_stage", "River")),
            str(sel.get("special_scope", "private")), str(sel.get("anaconda", "off")),
            self.claim, str(sel.get("pineapple", "off")), int(sel.get("pine_count", 1)),
            _flag(sel.get("dice")), _flag(sel.get("bounty")),
            str(sel.get("wild", "off")), _flag(sel.get("auction")),
            str(sel.get("deck", "standard")))


# Which add-ons make sense together, agreed with the owner on 2026-11-10
# (docs/DECISIONS.md, "Combination rules"). Everything else is allowed.
BUILT_IN_TWIST = {"redriver": "Red River's extra rivers", "blackjack": "Blackjack's hit or stand",
                  "wallstreet": "Wall Street's market"}
BUILT_IN_WILDS = {"floors": "Elevator floors' free jokers"}


def _board_line(v: Variant) -> tuple[bool, int]:
    """(the community cards form ONE line, how many cards in it)."""
    comm = [g for g in v.board_groups if g.id not in ("special", "dice") and not g.optional]
    single = bool(comm) and len({g.row for g in comm}) == 1 and all(g.row_span == 1 for g in comm)
    return single, sum(g.size for g in comm)


def check_combo(st: "TableSettings", base: Variant) -> None:
    """Refuse combinations the owner ruled out, with a plain reason."""
    name = base.name.split(" · ")[0]
    ranks = {repr(c)[0] for c in base.deck}
    wilds = [w for w in (
        BUILT_IN_WILDS.get(base.id, ""),
        {"deuces": "Deuces wild", "oneeyed": "One-eyed jacks", "jokers": "2 jokers in the deck",
         "queen": "Follow the Queen", "river": "Wild river"}.get(st.wild, ""),
        {"joker": "the Joker card", "jumping": "the Jumping joker"}.get(st.special_kind, ""),
        "the Joker auction" if st.auction else "") if w]
    if len(wilds) > 1:
        raise VariantError(f"only one kind of wild card per game — you picked {' and '.join(wilds)}")
    if st.wild == "deuces" and "2" not in ranks:
        raise VariantError(f"{name} has no 2s, so Deuces wild can't happen")
    if st.bounty and not {"7", "2"} <= ranks:
        raise VariantError(f"{name} has no 7s or 2s, so the 7-2 bounty can't happen")
    single, size = _board_line(base)
    if st.dice:
        if not single or size != 5:
            raise VariantError("Dice is only for games with one board of 5 shared cards")
        if st.wild in ("river", "queen"):
            raise VariantError("Dice can't be combined with Wild river or Follow the Queen")
    if st.wild == "queen" and not single:
        raise VariantError("Follow the Queen needs a board that is one line of cards")
    if st.wild == "river":
        reveal = [s for s in base.stages if any(g not in ("special", "dice") for g in s.reveal)]
        last = reveal[-1] if reveal else None
        n = sum(base.group(g).size for g in last.reveal) if last else 0
        if not last or not last.name.startswith("River") or n != 1 or base.red_river:
            raise VariantError(f"Wild river needs exactly one shared river card, and {name} "
                               "doesn't have that")
    twists = [t for t in (BUILT_IN_TWIST.get(base.id, ""),
                          "Anaconda" if st.anaconda != "off" else "",
                          "Pineapple" if st.pineapple != "off" else "",
                          "Dice" if st.dice else "") if t]
    if len(twists) > 2:
        raise VariantError(f"at most two card twists per game — you picked {', '.join(twists)}")


def addon_blocks(settings: "TableSettings", player_count: int) -> dict:
    """For the dealer's-choice screen: which add-on choices can't be added to
    the current pick, and why. {field: {value: reason}}."""
    from dataclasses import replace as _replace
    lines = {"wild": ["deuces", "oneeyed", "jokers", "queen", "river"],
             "special_kind": ["joker", "poison", "jumping"], "auction": [True],
             "anaconda": ["flop", "every"], "pineapple": ["preflop", "flop", "every"],
             "dice": [True], "bounty": [True], "deck": ["short", "royal"]}
    out = {}
    for field_name, values in lines.items():
        for val in values:
            if getattr(settings, field_name) == val:
                continue                                  # already chosen
            trial = _replace(settings, **{field_name: val})
            if field_name == "anaconda":
                trial = _replace(trial, pineapple="off")
            if field_name == "pineapple":
                trial = _replace(trial, anaconda="off")
            try:
                trial.variant().validate(max(2, player_count))
            except (VariantError, ValueError, KeyError) as e:
                out.setdefault(field_name, {})[str(val).lower()] = str(e)
    return out


def preview_choice(settings: TableSettings, player_count: int) -> dict:
    """Name, rules and whether a dealer's choice can be dealt right now."""
    try:
        v = settings.variant()
    except (VariantError, ValueError, KeyError) as e:
        return {"ok": False, "reason": str(e), "name": "", "summary": [],
                "blocks": addon_blocks(settings, player_count)}
    try:
        v.validate(player_count)
        ok, why = True, ""
    except VariantError as e:
        ok, why = False, str(e)
    return {"ok": ok, "reason": why, "name": v.name, "summary": list(v.summary),
            "blocks": addon_blocks(settings, player_count)}


def random_choice(player_count: int, rng=None) -> dict:
    """A random, dealable choice: any family, any options, maybe a special
    card and maybe Anaconda."""
    from .variants import FAMILIES
    rng = rng or secrets.SystemRandom()
    for _ in range(400):
        fam = rng.choice(list(FAMILIES.values()))
        opts = {o.key: rng.choice(o.choices)[0] for o in fam.options}
        sel = {"variant_id": fam.id, "options": opts, "special_kind": "none",
               "special_stage": "River", "special_scope": "private", "anaconda": "off",
               "pineapple": "off", "pine_count": 1, "dice": False, "bounty": False,
               "wild": "off", "auction": False, "deck": "standard"}
        if rng.random() < 0.2:
            sel["deck"] = rng.choice(["short", "royal"])
        if rng.random() < 0.3:
            sel["wild"] = rng.choice(["deuces", "oneeyed", "jokers", "queen", "river"])
        if rng.random() < 0.12:
            sel["auction"] = True
        if rng.random() < 0.5:
            sel["special_kind"] = rng.choice(["joker", "poison", "jumping"])
            sel["special_stage"] = rng.choice(["Flop", "Turn", "River"])
            sel["special_scope"] = "all" if rng.random() < 0.25 else "private"
        if rng.random() < 0.25:
            sel["anaconda"] = rng.choice(["flop", "every"])
        elif rng.random() < 0.2:
            sel["pineapple"] = rng.choice(["preflop", "flop", "every"])
            sel["pine_count"] = rng.choice([1, 1, 2])
        if rng.random() < 0.2:
            sel["dice"] = True
        if rng.random() < 0.15:
            sel["bounty"] = True
        if preview_choice(TableSettings().with_choice(sel), player_count)["ok"]:
            return sel
    return {"variant_id": "classic", "options": {}}


@dataclass
class Seat:
    index: int
    name: str
    is_bot: bool
    stack: int
    rebuys: int = 0
    bot_level: str = ""


@dataclass
class Table:
    seat_count: int = 6
    settings: TableSettings = field(default_factory=TableSettings)
    rng: random.Random | None = None          # None -> secure randomness

    def __post_init__(self):
        self.settings.validate()
        self.seats: list[Seat | None] = [None] * self.seat_count
        self.pending_settings: TableSettings | None = None
        self.button: int | None = None
        self.hand: HandEngine | None = None
        self.hand_settings: TableSettings | None = None
        self.hand_no = 0
        self.seq = 0
        self.chips_added = 0

    # ------------------------------------------------------------ seating
    def sit(self, seat: int, name: str, is_bot: bool = False,
            stack: int | None = None, bot_level: str = "") -> Seat:
        if not 0 <= seat < self.seat_count:
            raise ValueError("no such seat")
        if self.seats[seat] is not None:
            raise ValueError("seat is taken")
        s = Seat(seat, name, is_bot, stack if stack is not None else self.settings.starting_stack,
                 bot_level=bot_level)
        self.seats[seat] = s
        self.chips_added += s.stack
        self.seq += 1
        return s

    def rebuy(self, seat: int) -> None:
        s = self.seats[seat]
        if s is None:
            raise ValueError("empty seat")
        if self.hand_in_progress and seat in self.hand.pk_of:
            raise IllegalAction("you can rebuy between hands")
        if s.stack > 0:
            raise IllegalAction("rebuy is only for busted players")
        s.stack = self.settings.starting_stack
        s.rebuys += 1
        self.chips_added += s.stack
        self.seq += 1

    def stand(self, seat: int) -> int:
        """Remove a player (or bot) and their chips from the table. Only
        between hands for anyone dealt into the current hand."""
        s = self.seats[seat] if 0 <= seat < self.seat_count else None
        if s is None:
            raise ValueError("empty seat")
        if self.hand_in_progress and seat in self.hand.pk_of:
            raise IllegalAction("players can leave the table between hands")
        self.seats[seat] = None
        self.chips_added -= s.stack
        self.seq += 1
        return s.stack

    def time_out(self, seat: int, why: str = "ran out of time") -> str:
        """The player ran out of time (or has left): check if free, else fold;
        at a showdown choice / Anaconda pass, choose for them."""
        if not self.hand_in_progress:
            raise IllegalAction("no hand in progress")
        h = self.hand
        turn = h.phase_turn
        if turn and turn[1] == seat:
            what = h.time_out_phase(seat)
        elif seat in h.pass_awaiting:
            h.auto_pass(seat); what = "pass"
        elif seat in h.awaiting:
            h.auto_declare(seat); what = "declare"
        elif h.actor_seat == seat:
            L = h.legal_actions(seat)
            what = "check" if L.check else "fold"
            h._log("timeout", f"{h._name(seat)} {why}", seat=seat)
            h.act(seat, what)
        else:
            raise IllegalAction("nothing to do for that seat")
        self._sync_stacks_if_done()
        self.seq += 1
        return what

    def change_settings(self, new: TableSettings) -> None:
        """Takes effect at the start of the next hand, never mid-hand."""
        new.validate()
        if self.hand_in_progress:
            self.pending_settings = new
        else:
            self.settings = new
        self.seq += 1

    # ------------------------------------------------------------ hands
    @property
    def hand_in_progress(self) -> bool:
        return self.hand is not None and not self.hand.finished

    def funded_seats(self) -> list[int]:
        return [s.index for s in self.seats if s is not None and s.stack > 0]

    def _next_funded(self, after: int, funded: list[int]) -> int:
        for k in range(1, self.seat_count + 1):
            i = (after + k) % self.seat_count
            if i in funded:
                return i
        raise RuntimeError("no funded seat")

    def can_start_hand(self) -> tuple[bool, str]:
        if self.hand_in_progress:
            return False, "a hand is in progress"
        settings = self.pending_settings or self.settings
        try:
            settings.variant().validate(len(self.funded_seats()))
        except VariantError as e:
            return False, str(e)
        return True, ""

    def start_hand(self, shoe: Shoe | None = None,
                   force_button: int | None = None) -> HandEngine:
        """Deal a new hand. ``shoe`` and ``force_button`` are for tests."""
        ok, why = self.can_start_hand()
        if not ok:
            raise IllegalAction(why)
        if self.pending_settings:
            self.settings, self.pending_settings = self.pending_settings, None
        self.hand_settings = self.settings
        variant = self.settings.variant()
        funded = self.funded_seats()

        if force_button is not None:
            if force_button not in funded:
                raise ValueError("forced button seat has no chips")
            self.button = force_button
        elif self.button is None:
            self.button = (self.rng or secrets.SystemRandom()).choice(funded)
        else:
            self.button = self._next_funded(self.button, funded)

        order, i = [], self.button
        for _ in range(len(funded)):
            i = self._next_funded(i, funded)
            order.append(i)
        assert order[-1] == self.button

        shoe = shoe or Shoe(variant.deck, self.rng)
        self.hand_no += 1
        self.hand = HandEngine(
            variant, order, [self.seats[s].stack for s in order],
            self.settings.small_blind, self.settings.big_blind, shoe,
            names={s: self.seats[s].name for s in order},
            auto_seats={s for s in order if self.seats[s].is_bot})
        self._sync_stacks_if_done()
        self.seq += 1
        return self.hand

    def _check_seq(self, seq):
        if seq is not None and seq != self.seq:
            raise IllegalAction("that action is out of date; the table has moved on")

    def act(self, seat: int, kind: str, amount: int | None = None,
            seq: int | None = None) -> None:
        self._check_seq(seq)
        if not self.hand_in_progress:
            raise IllegalAction("no hand in progress")
        if self.hand.actor_seat != seat:
            raise IllegalAction("it is not your turn")
        self.hand.act(seat, kind, amount)
        self._sync_stacks_if_done()
        self.seq += 1

    def declare(self, seat: int, declaration: dict, seq: int | None = None) -> None:
        """A human's showdown choice (split cards between rows / pick cards)."""
        self._check_seq(seq)
        if not self.hand_in_progress:
            raise IllegalAction("no hand in progress")
        self.hand.declare(seat, declaration)
        self._sync_stacks_if_done()
        self.seq += 1

    def pass_card(self, seat: int, card: str, seq: int | None = None) -> None:
        """Anaconda: a human passes one face-down card to the player on their left."""
        self._check_seq(seq)
        if not self.hand_in_progress:
            raise IllegalAction("no hand in progress")
        self.hand.pass_card(seat, card)
        self._sync_stacks_if_done()
        self.seq += 1

    def phase_action(self, seat: int, kind: str, card: str = "", seq: int | None = None) -> None:
        """Blackjack Hold'em: "hit" / "stand". Wall Street: "buy" (card) / "market_fold"."""
        self._check_seq(seq)
        if not self.hand_in_progress:
            raise IllegalAction("no hand in progress")
        h = self.hand
        if kind == "hit":
            h.hit(seat)
        elif kind == "stand":
            h.stand(seat)
        elif kind == "buy":
            h.buy(seat, card)
        elif kind == "market_fold":
            h.market_fold(seat)
        elif kind == "bid":
            try:
                h.bid(seat, int(card))
            except (TypeError, ValueError) as e:
                if isinstance(e, IllegalAction):
                    raise
                raise IllegalAction("bid must be a whole number") from None
        elif kind == "drop":
            h.drop(seat)
        else:
            raise IllegalAction(f"unknown action {kind!r}")
        self._sync_stacks_if_done()
        self.seq += 1

    def _sync_stacks_if_done(self) -> None:
        if self.hand and self.hand.finished:
            self._pay_bounty()
            for seat in self.hand.seat_ids:
                self.seats[seat].stack = self.hand.stack(seat)

    def _pay_bounty(self) -> None:
        """7-2 bounty: a pot winner holding a 7 and a 2 collects BOUNTY_BB big
        blinds from every other player dealt in (as much as they have)."""
        h = self.hand
        if not (self.hand_settings and self.hand_settings.bounty) or getattr(h, "_bounty_done", False):
            return
        h._bounty_done = True
        if not h.result:
            return
        winners = sorted({w["seat"] for p in h.result["pots"] for w in p["winners"]})
        paid = []
        for w in winners:
            ranks = {repr(c)[0] for c in h.dealt[w]}
            if not {"7", "2"} <= ranks:
                continue
            if w not in h.shown:                      # show the 7-2 to claim it
                h.shown[w] = h.hole_cards(w)
            amount = BOUNTY_BB * self.hand_settings.big_blind
            total = 0
            st = h.state
            for other in h.seat_ids:
                if other == w:
                    continue
                pay = min(amount, st.stacks[h.pk_of[other]])
                st.stacks[h.pk_of[other]] -= pay
                st.stacks[h.pk_of[w]] += pay
                total += pay
            h._log("bounty", f"7-2 BOUNTY! {h._name(w)} wins with a 7 and a 2 and collects "
                   f"{total} ({amount} from each player)", seat=w, amount=total)
            paid.append({"seat": w, "amount": total})
        if paid:
            h.result["bounty"] = paid
            for p in paid:
                h.result["net"][p["seat"]] = h.result["net"].get(p["seat"], 0) + p["amount"]
            for s in h.seat_ids:                       # keep net = final - start for everyone
                i = h.pk_of[s]
                h.result["net"][s] = h.state.stacks[i] - h.starting_stacks[i]

    # ------------------------------------------------------------ checks
    def total_chips(self) -> int:
        """All chips at the table, including those in the current pot."""
        if self.hand_in_progress:
            in_hand = set(self.hand.seat_ids)
            outside = sum(s.stack for s in self.seats if s and s.index not in in_hand)
            return outside + sum(self.hand.stack(x) for x in in_hand) + self.hand.total_pot()
        return sum(s.stack for s in self.seats if s)

    # ------------------------------------------------------------ views
    def view(self, viewer: int | None) -> dict:
        """Everything ``viewer`` (a seat, or None for a spectator) may see.
        Never includes the deck or unrevealed opponent cards."""
        h = self.hand
        live = self.hand_in_progress
        settings = self.hand_settings if live else self.settings
        variant = h.variant if h else settings.variant()
        roles = h.roles() if h else {}
        seats = []
        for i, s in enumerate(self.seats):
            if s is None:
                seats.append({"index": i, "empty": True})
                continue
            d = {"index": i, "empty": False, "name": s.name, "is_bot": s.is_bot,
                 "bot_level": s.bot_level,
                 "stack": s.stack, "bet": 0, "status": "out", "cards": None,
                 "card_count": 0, "role": "", "is_button": i == self.button,
                 "declaring": False}
            if h is not None and i in h.pk_of:
                d["role"] = roles.get(i, "")
                if live:
                    d["stack"] = h.stack(i)
                    d["bet"] = h.bet(i)
                if h.folded(i):
                    d["status"] = "folded"
                elif live and h.stack(i) == 0:
                    d["status"] = "all-in"
                else:
                    d["status"] = "in"
                d["card_count"] = len(h.dealt[i])
                d["declaring"] = i in h.awaiting
                if i in h.dead:                        # bust (Blackjack) / market fold
                    d["status"] = "folded"
                    d["out_reason"] = h.dead[i]
                d["discarded"] = len(h.discarded[i])
                d["bought"] = len(h.bought[i])
                if i == viewer:
                    d["cards"] = h.hole_cards(i)
                elif i in h.shown:
                    d["cards"] = list(h.shown[i])
                elif not h.folded(i):
                    d["cards"] = h.public_cards(i)      # face-up cards only (or None)
                # face-up cards are public: everyone may know which ones they are
                d["up_cards"] = [] if h.folded(i) else \
                    [repr(c) for c in h.dealt[i] if c in h.up_cards]
                d["passing"] = i in h.pass_awaiting
            elif s.stack == 0:
                d["status"] = "busted"
            seats.append(d)

        out = {
            "seq": self.seq,
            "hand_no": self.hand_no,
            "you": viewer,
            "settings": settings.as_dict(),
            "pending_settings": self.pending_settings.as_dict() if self.pending_settings else None,
            "variant": variant.describe(),
            "button": self.button,
            "seats": seats,
            "hand_active": live,
            "stage": h.street_name if h else None,
            "board": h.board() if h else {},
            "pots": h.pots() if h else [],
            "total_pot": h.total_pot() if h else 0,
            "chips_on_table": self.total_chips(),
            "actor": h.actor_seat if live else None,
            "legal": None,
            "declare": None,
            "awaiting": sorted(h.awaiting) if live else [],
            "your_hand": [],
            "history": list(h.history) if h else [],
            "result": h.result if h and h.finished else None,
            # names of everyone dealt into the hand (someone may have left since)
            "names": {str(k): v for k, v in h.names.items()} if h else {},
            # private: only the viewer's own "learn from this hand" notes
            "lessons": (h.lessons.get(viewer, []) if h and h.finished and viewer is not None else []),
            "catalogue": None,
        }
        if live and viewer is not None and h.actor_seat == viewer:
            out["legal"] = h.legal_actions(viewer).as_dict()
        if live and viewer is not None and viewer in h.awaiting:
            out["declare"] = {"hole": h.hole_cards(viewer)}
        out["pass"] = None
        out["pass_awaiting"] = sorted(h.pass_awaiting) if live else []
        if live and viewer is not None and viewer in h.pass_awaiting:
            out["pass"] = {"cards": [repr(c) for c in h.dealt[viewer] if c not in h.up_cards]}
        if h is not None and viewer in h.pk_of and live:
            out["your_hand"] = h.current_hand_labels(viewer)
        # learning hint: best / second-best possible hands (board only, same for all)
        out["nuts"] = h.nuts() if live and viewer is not None else []
        # new phases: whose turn it is (public) and what the viewer may do
        turn = h.phase_turn if live else None
        out["phase"] = {"kind": turn[0], "seat": turn[1]} if turn else None
        out["dice"] = list(h.dice_rolls) if h else []
        out["market"] = None
        if h is not None and h.variant.market and h.market_state == "active":
            out["market"] = {"cards": [{"code": repr(c), "price": h.price(c)} for c in h.market],
                             "pot": h.market_pot, "buys": h.variant.market[1]}
        if turn and turn[1] == viewer and turn[0] == "hit":
            from .evaluate import bj_total
            out["hit"] = {"total": bj_total(h.dealt[viewer])}
        if turn and turn[1] == viewer and turn[0] == "buy":
            out["buy"] = {"can_afford": [repr(c) for c in h.market if h.price(c) < h.stack(viewer)]}
        out["auction"] = None
        if h is not None and h.auction_state == "active":
            out["auction"] = {"bid": h.auction_bid, "leader": h.auction_leader,
                              "min": h.auction_min(), "out": sorted(h.auction_out)}
            if turn and turn == ("bid", viewer):
                out["auction"]["max"] = h.stack(viewer) - 1
        # which cards are wild / poisoned right now (your own + the board)
        out["wild_codes"], out["dead_codes"] = [], []
        if h is not None:
            from . import evaluate as _ev
            board = h.board_cards()
            mine = h.dealt[viewer] if viewer in h.pk_of else []
            prep = {repr(_ev.real(e)): e for e in _ev.prepare(h.variant, mine, board)}
            for c in mine:
                code = repr(c)
                if code not in prep:
                    out["dead_codes"].append(code)
                elif isinstance(prep[code], _ev.Wild):
                    out["wild_codes"].append(code)
            pb = _ev.prepare_board(h.variant, board)
            for gid, cards in board.items():
                played = {repr(_ev.real(e)): e for e in pb.get(gid, [])}
                for c in cards:
                    code = repr(c)
                    if code not in played and gid != "special":
                        out["dead_codes"].append(code)
                    elif isinstance(played.get(code), _ev.Wild):
                        out["wild_codes"].append(code)
        if live and viewer in getattr(h, "pass_awaiting", ()) and h.variant.pass_mode == "discard":
            out["discard"] = {"count": h.variant.pass_count,
                              "chosen": [repr(c) for c in h.pass_choices.get(viewer, [])]}
        if not live:
            out["catalogue"] = catalogue()
        ok, why = self.can_start_hand()
        out["can_start"] = ok
        out["cannot_start_reason"] = why
        return out
