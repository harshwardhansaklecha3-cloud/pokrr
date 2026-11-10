"""The POKRR variation library.

Each preset = a name, a short pitch, a set of dealer options (e.g. "fix 2"
vs "012"), and a ``build(options)`` function returning a ``Variant``.
Rules here are exactly as agreed with the user (see docs/DECISIONS.md).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable

from ..cards import STANDARD_52
from .base import BoardGroup, HandRow, Stage, Variant, VariantError


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    choices: tuple[tuple[str, str], ...]   # (value, label)
    default: str


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    pitch: str
    options: tuple[Option, ...]
    build: Callable[[dict], Variant]

    def resolve(self, given: dict | None) -> dict:
        given = given or {}
        out = {}
        for o in self.options:
            v = given.get(o.key, o.default)
            if v not in {c[0] for c in o.choices}:
                raise VariantError(f"{self.name}: invalid choice {v!r} for {o.label}")
            out[o.key] = v
        return out

    def make(self, given: dict | None = None) -> Variant:
        opts = self.resolve(given)
        v = self.build(opts)
        v.validate()
        return v

    def combos(self):
        keys = [o.key for o in self.options]
        for values in itertools.product(*[[c[0] for c in o.choices] for o in self.options]):
            yield dict(zip(keys, values))


# ---------------------------------------------------------------- helpers
def hole_rule(choice: str, n_private: int) -> tuple[int, ...]:
    if choice == "any":
        return tuple(range(0, min(n_private, 5) + 1))
    if choice.startswith("fix"):
        return (int(choice[3:]),)
    raise VariantError(f"unknown hand rule {choice!r}")


def rule_text(use: tuple[int, ...], alloc_or_hole: int) -> str:
    if len(use) == 1:
        k = use[0]
        return f"use exactly {k} private card{'s' if k != 1 else ''} + {5 - k} community"
    return f"any 5 cards ({'-'.join(map(str, use))} private)"


ANY_FIX2 = Option("hand_rule", "Hand rule",
                  (("any", "012 — any 5 cards"), ("fix2", "Fix 2 — exactly 2 private")), "any")
FIX2_ANY = Option("hand_rule", "Hand rule",
                  (("fix2", "Fix 2 — exactly 2 private"), ("any", "Any 5 cards")), "fix2")
SPLIT_SHARED = Option("cards", "Private cards across rows",
                      (("split", "Split — each card in one row only"),
                       ("shared", "Shared — use cards in both rows")), "split")

STD_STAGES_1ROW = (
    Stage("Preflop"), Stage("Flop", reveal=("flop",), burn=True),
    Stage("Turn", reveal=("turn",), burn=True), Stage("River", reveal=("river",), burn=True),
)


def _with_hole(stages, n):
    first = Stage(stages[0].name, hole_cards=n)
    return (first,) + tuple(stages[1:])


def _opts(d: dict) -> tuple:
    return tuple(sorted(d.items()))


# ---------------------------------------------------------------- 1. Hold'em
def build_holdem(o):
    use = hole_rule(o["hand_rule"], 2)
    return Variant(
        id="holdem", name="Texas Hold'em", options=_opts(o),
        summary=("2 private cards each; 5 community cards (flop 3, turn 1, river 1).",
                 "Betting: preflop, flop, turn, river.",
                 f"Hand: {rule_text(use, 2)}." + (" Classic Hold'em." if o["hand_rule"] == "any" else "")),
        deck=STANDARD_52, stages=_with_hole(STD_STAGES_1ROW, 2),
        board_groups=(BoardGroup("flop", "Flop", 3, col=0), BoardGroup("turn", "Turn", 1, col=1),
                      BoardGroup("river", "River", 1, col=2)),
        rows=(HandRow("main", "Board", ("flop", "turn", "river"), use),),
        max_players=10)


# ---------------------------------------------------------------- 2. Omaha
def build_omaha(o):
    use = hole_rule(o["hand_rule"], 4)
    return Variant(
        id="omaha", name="Omaha", options=_opts(o),
        summary=("4 private cards each; 5 community cards (flop 3, turn 1, river 1).",
                 "Betting: preflop, flop, turn, river. No-limit.",
                 f"Hand: {rule_text(use, 4)}."),
        deck=STANDARD_52, stages=_with_hole(STD_STAGES_1ROW, 4),
        board_groups=(BoardGroup("flop", "Flop", 3, col=0), BoardGroup("turn", "Turn", 1, col=1),
                      BoardGroup("river", "River", 1, col=2)),
        rows=(HandRow("main", "Board", ("flop", "turn", "river"), use),),
        max_players=10)


# ---------------------------------------------------------------- 3/4. Double board
def _double(o, vid, name, n_private):
    split = o["cards"] == "split"
    alloc = n_private // 2 if split else None
    use = hole_rule(o["hand_rule"], alloc or n_private)
    groups = []
    for r, tag in enumerate("AB"):
        groups += [BoardGroup(f"flop{tag}", f"Flop {tag}", 3, row=r, col=0),
                   BoardGroup(f"turn{tag}", f"Turn {tag}", 1, row=r, col=1),
                   BoardGroup(f"river{tag}", f"River {tag}", 1, row=r, col=2)]
    stages = (Stage("Preflop", hole_cards=n_private),
              Stage("Flop", reveal=("flopA", "flopB"), burn=True),
              Stage("Turn", reveal=("turnA", "turnB"), burn=True),
              Stage("River", reveal=("riverA", "riverB"), burn=True))
    rows = tuple(HandRow(t, f"Row {t}", (f"flop{t}", f"turn{t}", f"river{t}"), use, alloc)
                 for t in "AB")
    split_txt = (f"Before showdown, split your cards: {alloc} to Row A, {alloc} to Row B "
                 "(a card can't play in both)." if split
                 else "Your private cards can be used in both rows.")
    return Variant(
        id=vid, name=name, options=_opts(o),
        summary=(f"{n_private} private cards each; two rows of 5 community cards.",
                 "One betting round per street, covering both rows.",
                 f"Each row: {rule_text(use, alloc or n_private)}. {split_txt}",
                 "Pot is split half per row; win both rows to take it all."),
        deck=STANDARD_52, stages=stages, board_groups=tuple(groups), rows=rows,
        scoring="split", max_players=10)


def build_double_holdem(o):
    return _double(o, "double_holdem", "Double Board Hold'em", 4)


def build_double_omaha(o):
    return _double(o, "double_omaha", "Double Board Omaha", int(o["private"]))


# ---------------------------------------------------------------- 5. Pyramid
def build_pyramid(o):
    use = hole_rule(o["hand_rule"], 2)
    tiers = [("t5", "Row of 5", 5, 4), ("t4", "Row of 4", 4, 3), ("t3", "Row of 3", 3, 2),
             ("t2", "Row of 2", 2, 1), ("t1", "Top card", 1, 0)]
    return Variant(
        id="pyramid", name="Pyramid", options=_opts(o), selection="declare",
        summary=("2 private cards each. Pyramid of 15 community cards: rows of 5, 4, 3, 2, 1.",
                 "Flop reveals the rows of 5, 4 and 3; turn reveals the row of 2; "
                 "river reveals the top card.",
                 "Your community cards: at most one from each pyramid row.",
                 f"Hand: {rule_text(use, 2)}.",
                 "At showdown YOU pick your cards — a weaker pick counts. Bots pick their best."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=2),
                Stage("Flop", reveal=("t5", "t4", "t3"), burn=True),
                Stage("Turn", reveal=("t2",), burn=True),
                Stage("River", reveal=("t1",), burn=True)),
        board_groups=tuple(BoardGroup(g, label, n, row=row) for g, label, n, row in tiers),
        rows=(HandRow("main", "Pyramid", ("t5", "t4", "t3", "t2", "t1"), use,
                      one_per_group=True),),
        max_players=10)


# ---------------------------------------------------------------- 6. Elevator
def build_elevator(o):
    use = hole_rule(o["hand_rule"], 2)
    groups = [BoardGroup(f"r{i}", f"Row {i}", 3, row=i - 1, col=0) for i in (1, 2, 3)]
    groups += [BoardGroup("e1", "Elevator 1 (turn)", 1, row=0, col=1, row_span=3),
               BoardGroup("e2", "Elevator 2 (river)", 1, row=0, col=2, row_span=3)]
    return Variant(
        id="elevator", name="Elevator", options=_opts(o),
        summary=("6 private cards each. Flop: three rows of 3 cards.",
                 "Turn and river are the two 'elevator' cards — shared by all three rows.",
                 "Before showdown, split your 6 cards into 3 pairs: one pair per row.",
                 f"Each row: your pair + its 3 cards + the 2 elevator cards; {rule_text(use, 2)}.",
                 "Showdown row by row; each row wins 1/3 of the pot."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=6),
                Stage("Flop", reveal=("r1", "r2", "r3"), burn=True),
                Stage("Turn", reveal=("e1",), burn=True),
                Stage("River", reveal=("e2",), burn=True)),
        board_groups=tuple(groups),
        rows=tuple(HandRow(f"R{i}", f"Row {i}", (f"r{i}", "e1", "e2"), use, hole_alloc=2)
                   for i in (1, 2, 3)),
        scoring="split", max_players=8)


# ---------------------------------------------------------------- 7. Twin Rows
def build_twin_rows(o):
    use = hole_rule(o["hand_rule"], 3)
    return Variant(
        id="twin_rows", name="Twin Rows", options=_opts(o), scoring="best",
        summary=("3 private cards each.",
                 "Flop: two rows of 3. Turn: 1 card shared by both rows. River: 1 card per row.",
                 f"Each row: {rule_text(use, 3)}.",
                 "Single pot: your best hand from either row; the best hand at the table wins it all."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=3),
                Stage("Flop", reveal=("flopA", "flopB"), burn=True),
                Stage("Turn", reveal=("turn",), burn=True),
                Stage("River", reveal=("riverA", "riverB"))),     # no burn, as dealt by the user
        board_groups=(BoardGroup("flopA", "Flop A", 3, row=0, col=0),
                      BoardGroup("flopB", "Flop B", 3, row=1, col=0),
                      BoardGroup("turn", "Turn (shared)", 1, row=0, col=1, row_span=2),
                      BoardGroup("riverA", "River A", 1, row=0, col=2),
                      BoardGroup("riverB", "River B", 1, row=1, col=2)),
        rows=(HandRow("A", "Row A", ("flopA", "turn", "riverA"), use),
              HandRow("B", "Row B", ("flopB", "turn", "riverB"), use)),
        max_players=10)


# ---------------------------------------------------------------- 8. 2or3
def build_two_or_three(o):
    common_turn = o["layout"] == "common_turn"
    if common_turn:
        groups = (BoardGroup("flopT", "Top flop", 3, row=0, col=0),
                  BoardGroup("flopB", "Bottom flop", 2, row=1, col=0),
                  BoardGroup("turn", "Turn (shared)", 1, row=0, col=1, row_span=2),
                  BoardGroup("riverT", "Top river", 1, row=0, col=2),
                  BoardGroup("riverB", "Bottom river", 1, row=1, col=2))
        turn, river = ("turn",), ("riverT", "riverB")
        top, bot = ("flopT", "turn", "riverT"), ("flopB", "turn", "riverB")
        lay = "Turn is shared by both rows; each row gets its own river."
    else:
        groups = (BoardGroup("flopT", "Top flop", 3, row=0, col=0),
                  BoardGroup("flopB", "Bottom flop", 2, row=1, col=0),
                  BoardGroup("turnT", "Top turn", 1, row=0, col=1),
                  BoardGroup("turnB", "Bottom turn", 1, row=1, col=1),
                  BoardGroup("river", "River (shared)", 1, row=0, col=2, row_span=2))
        turn, river = ("turnT", "turnB"), ("river",)
        top, bot = ("flopT", "turnT", "river"), ("flopB", "turnB", "river")
        lay = "Each row gets its own turn; the river is shared."
    return Variant(
        id="two_or_three", name="2or3", options=_opts(o), scoring="best",
        summary=("5 private cards each.",
                 "Flop: top row of 3, bottom row of 2. " + lay,
                 "Top row (5 community cards): use exactly 2 private cards.",
                 "Bottom row (4 community cards): use exactly 3 private cards.",
                 "Single pot: your better row counts; the best hand at the table wins it all."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=5),
                Stage("Flop", reveal=("flopT", "flopB"), burn=True),
                Stage("Turn", reveal=turn, burn=True),
                Stage("River", reveal=river, burn=True)),
        board_groups=groups,
        rows=(HandRow("top", "Top row (2 from hand)", top, (2,)),
              HandRow("bottom", "Bottom row (3 from hand)", bot, (3,))),
        max_players=8)


# ---------------------------------------------------------------- 9. 3or3or2
def build_three_three_two(o):
    """The user's 'advanced 2or3': flop 3+3+2, a shared turn, then 1+1+1
    river. ASSUMED (by analogy with 2or3, awaiting confirmation): 5 private
    cards; rows with a 3-card flop use exactly 2 private, the 2-card-flop row
    uses exactly 3; single pot, best row wins."""
    groups = (BoardGroup("flop1", "Flop 1", 3, row=0, col=0),
              BoardGroup("flop2", "Flop 2", 3, row=1, col=0),
              BoardGroup("flop3", "Flop 3", 2, row=2, col=0),
              BoardGroup("turn", "Turn (shared)", 1, row=0, col=1, row_span=3),
              BoardGroup("river1", "River 1", 1, row=0, col=2),
              BoardGroup("river2", "River 2", 1, row=1, col=2),
              BoardGroup("river3", "River 3", 1, row=2, col=2))
    return Variant(
        id="three_three_two", name="3or3or2", options=_opts(o), scoring="best",
        summary=("5 private cards each.",
                 "Flop: three rows of 3, 3 and 2 cards. Turn: 1 card shared by all rows. "
                 "River: 1 card per row.",
                 "Rows 1 and 2 (5 community cards): use exactly 2 private cards.",
                 "Row 3 (4 community cards): use exactly 3 private cards.",
                 "Single pot: your best row counts; the best hand at the table wins it all."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=5),
                Stage("Flop", reveal=("flop1", "flop2", "flop3"), burn=True),
                Stage("Turn", reveal=("turn",), burn=True),
                Stage("River", reveal=("river1", "river2", "river3"), burn=True)),
        board_groups=groups,
        rows=(HandRow("r1", "Row 1 (2 from hand)", ("flop1", "turn", "river1"), (2,)),
              HandRow("r2", "Row 2 (2 from hand)", ("flop2", "turn", "river2"), (2,)),
              HandRow("r3", "Row 3 (3 from hand)", ("flop3", "turn", "river3"), (3,))),
        max_players=7)


PRESETS: dict[str, Preset] = {p.id: p for p in (
    Preset("holdem", "Texas Hold'em", "2 private · 5 community", (ANY_FIX2,), build_holdem),
    Preset("omaha", "Omaha", "4 private · exactly 2 + 3", (FIX2_ANY,), build_omaha),
    Preset("double_holdem", "Double Board Hold'em", "4 private · 2 rows · pot split per row",
           (SPLIT_SHARED, ANY_FIX2), build_double_holdem),
    Preset("double_omaha", "Double Board Omaha", "6 or 8 private · 2 rows · pot split per row",
           (Option("private", "Private cards", (("6", "6 cards"), ("8", "8 cards")), "6"),
            SPLIT_SHARED, FIX2_ANY), build_double_omaha),
    Preset("pyramid", "Pyramid", "15-card pyramid · you pick one per row",
           (ANY_FIX2,), build_pyramid),
    Preset("elevator", "Elevator", "6 private · 3 rows · elevator cards · pot in thirds",
           (ANY_FIX2,), build_elevator),
    Preset("twin_rows", "Twin Rows", "3 private · 2 rows · shared turn · best row wins all",
           (Option("hand_rule", "Hand rule",
                   (("any", "0123 — any 5 cards"), ("fix2", "Fix 2"), ("fix3", "Fix 3")), "any"),),
           build_twin_rows),
    Preset("two_or_three", "2or3", "5 private · top row uses 2, bottom uses 3",
           (Option("layout", "Shared card",
                   (("common_turn", "Shared turn, 1+1 river"),
                    ("common_river", "1+1 turn, shared river")), "common_turn"),),
           build_two_or_three),
    Preset("three_three_two", "3or3or2", "5 private · 3 rows · shared turn · best row wins",
           (), build_three_three_two),
)}


def get_preset(preset_id: str) -> Preset:
    try:
        return PRESETS[preset_id]
    except KeyError:
        raise VariantError(f"unknown variation {preset_id!r}") from None


def build_variant(preset_id: str, options: dict | None = None) -> Variant:
    return get_preset(preset_id).make(options)


def catalogue(player_count: int | None) -> list[dict]:
    """Every preset with every option combination, for the dealer's picker."""
    out = []
    for p in PRESETS.values():
        combos = []
        for c in p.combos():
            v = p.make(c)
            try:
                v.validate(player_count)
                ok, why = True, ""
            except VariantError as e:
                ok, why = False, str(e)
            combos.append({"options": c, "summary": list(v.summary), "ok": ok, "reason": why})
        out.append({"id": p.id, "name": p.name, "pitch": p.pitch,
                    "options": [{"key": o.key, "label": o.label, "default": o.default,
                                 "choices": [{"value": a, "label": b} for a, b in o.choices]}
                                for o in p.options],
                    "combos": combos})
    return out
