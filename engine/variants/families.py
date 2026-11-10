"""Game families: the dealer picks a broad game, then its adjustable parts.

    Classic board      5 community cards; private cards 2-6; Fix 2 / Fix 3 / any
                       (Hold'em = 2 cards + any;  Omaha = 4 cards + Fix 2)
    Double board       two completely separate boards, pot split per board
    Shared-card rows   rows of flop cards that SHARE a turn and/or river card:
                       Twin Rows, 2or3, 3or3or2, Elevator layouts
    Pyramid            15-card pyramid, one card per pyramid row
    Personal board     3 common flop cards + your own face-up turn and river
    Poker Patti        2 cards play poker with the board, 3 play Teen Patti
    Elevator floors    floors of 1, 2, 3 flop cards + shared turn/river; free
                       jokers on the low floors (2, 1, 0); at least 2 private
    Tic-tac-toe        3x3 grid (corners, edges, centre); 2 private + one line

Add-ons that work with every family (applied in TableSettings): a special
card (Joker / Poison / Jumping joker) and Anaconda passing.
"""
from __future__ import annotations

from ..cards import STANDARD_52
from .base import BoardGroup, HandRow, Stage, Variant, VariantError
from .presets import Option, Preset, _opts, rule_text


def _use(rule: str, n_hole: int, n_board: int) -> tuple[int, ...]:
    """Allowed private-card counts for a row."""
    if rule == "any":
        return tuple(k for k in range(0, min(n_hole, 5) + 1) if 5 - k <= n_board)
    if rule == "fixed":                       # 5 community -> 2 private, 4 -> 3
        return (max(0, 7 - n_board),)
    if rule.startswith("fix"):
        return (int(rule[3:]),)
    raise VariantError(f"unknown hand rule {rule!r}")


PRIVATE = lambda vals, default: Option(               # noqa: E731
    "private", "Private cards", tuple((str(v), f"{v} cards") for v in vals), str(default))


# ---------------------------------------------------------------- Classic board
def build_classic(o):
    n, rule = int(o["private"]), o["rule"]
    use = _use(rule, n, 5)
    if n == 2 and rule == "any":
        name, vid = "Texas Hold'em", "classic"
    elif n == 4 and rule == "fix2":
        name, vid = "Omaha", "classic"
    else:
        name, vid = f"Classic board · {n} cards", "classic"
    return Variant(
        id=vid, name=name, options=_opts(o),
        summary=(f"{n} private cards each; 5 community cards (flop 3, turn 1, river 1).",
                 "Betting: preflop, flop, turn, river. No-limit.",
                 f"Hand: {rule_text(use, n)}."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n), Stage("Flop", reveal=("flop",), burn=True),
                Stage("Turn", reveal=("turn",), burn=True), Stage("River", reveal=("river",), burn=True)),
        board_groups=(BoardGroup("flop", "Flop", 3, col=0), BoardGroup("turn", "Turn", 1, col=1),
                      BoardGroup("river", "River", 1, col=2)),
        rows=(HandRow("main", "Board", ("flop", "turn", "river"), use),), max_players=10)


RULE3 = Option("rule", "Hand rule", (("any", "Any 5 cards (0-1-2…)"), ("fix2", "Fix 2 from hand"),
                                      ("fix3", "Fix 3 from hand")), "any")


# ---------------------------------------------------------------- Double board
def build_double(o):
    n, split, rule = int(o["private"]), o["cards"] == "split", o["rule"]
    alloc = n // 2 if split else None
    use = _use(rule, alloc or n, 5)
    groups, rows = [], []
    for r, t in enumerate("AB"):
        groups += [BoardGroup(f"flop{t}", f"Flop {t}", 3, row=r, col=0),
                   BoardGroup(f"turn{t}", f"Turn {t}", 1, row=r, col=1),
                   BoardGroup(f"river{t}", f"River {t}", 1, row=r, col=2)]
        rows.append(HandRow(t, f"Board {t}", (f"flop{t}", f"turn{t}", f"river{t}"), use, alloc))
    split_txt = (f"Before showdown, split your cards: {alloc} to Board A, {alloc} to Board B."
                 if split else "Your private cards play on both boards.")
    return Variant(
        id="double", name=f"Double board · {n} cards", options=_opts(o),
        summary=(f"{n} private cards each; two separate boards of 5 community cards.",
                 "One betting round per street, covering both boards.",
                 f"Each board: {rule_text(use, alloc or n)}. {split_txt}",
                 "Pot split half per board; win both to take it all."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n),
                Stage("Flop", reveal=("flopA", "flopB"), burn=True),
                Stage("Turn", reveal=("turnA", "turnB"), burn=True),
                Stage("River", reveal=("riverA", "riverB"), burn=True)),
        board_groups=tuple(groups), rows=tuple(rows), scoring="split", max_players=10)


# ---------------------------------------------------------------- Shared-card rows
LAYOUTS = {
    # name, flop sizes per row, turn shared?, river shared?, classic private, rule, pot
    "twin":   ("Twin Rows", (3, 3), True, False, 3, "any", "best"),
    "2or3":   ("2or3", (3, 2), True, False, 5, "fixed", "best"),
    "2or3r":  ("2or3 (shared river)", (3, 2), False, True, 5, "fixed", "best"),
    "3or3or2": ("3or3or2", (3, 3, 2), True, False, 5, "fixed", "best"),
    "elevator": ("Elevator", (3, 3, 3), True, True, 6, "any", "split"),
}


def build_rows(o):
    key = o["layout"]
    lname, flops, turn_shared, river_shared, c_priv, c_rule, c_pot = LAYOUTS[key]
    n = c_priv if o["private"] == "classic" else int(o["private"])
    rule = c_rule if o["rule"] == "classic" else o["rule"]
    pot = c_pot if o["pot"] == "classic" else o["pot"]
    k = len(flops)
    groups, rows = [], []
    for i, size in enumerate(flops):
        groups.append(BoardGroup(f"flop{i}", f"Flop {i + 1}", size, row=i, col=0))
    groups.append(BoardGroup("turn", "Turn (shared)", 1, row=0, col=1, row_span=k) if turn_shared
                  else None)
    groups = [g for g in groups if g]
    if not turn_shared:
        groups += [BoardGroup(f"turn{i}", f"Turn {i + 1}", 1, row=i, col=1) for i in range(k)]
    if river_shared:
        groups.append(BoardGroup("river", "River (shared)", 1, row=0, col=2, row_span=k))
    else:
        groups += [BoardGroup(f"river{i}", f"River {i + 1}", 1, row=i, col=2) for i in range(k)]
    alloc = n // k if pot == "split" else None
    for i, size in enumerate(flops):
        gids = (f"flop{i}", "turn" if turn_shared else f"turn{i}",
                "river" if river_shared else f"river{i}")
        use = _use(rule, alloc or n, size + 2)
        tag = f" ({use[0]} from hand)" if len(use) == 1 else ""
        rows.append(HandRow(f"r{i + 1}", f"Row {i + 1}{tag}", gids, use, alloc))
    classic = o["private"] == o["rule"] == o["pot"] == "classic"
    name = lname if classic else f"{lname} · custom"
    shared = " and ".join(x for x, s in (("turn", turn_shared), ("river", river_shared)) if s)
    flop_txt = " + ".join(map(str, flops))
    rule_lines = []
    for r in rows:
        rule_lines.append(f"{r.label.split(' (')[0]}: {rule_text(r.hole_use, alloc or n)}")
    if pot == "best":
        pot_txt = ("Single pot: each player's best row counts; the best hand at the table "
                   "wins it all. Rows never mix — a hand uses only its own row's cards.")
    else:
        pot_txt = (f"Before showdown split your {n} cards: {alloc} to each row. Showdown row "
                   f"by row; each row wins 1/{k} of the pot.")
    later_turn = "Turn: 1 card shared by all rows." if turn_shared else "Turn: 1 card per row."
    later_river = "River: 1 card shared by all rows." if river_shared else "River: 1 card per row."
    return Variant(
        id="rows", name=name, options=_opts(o), scoring=pot,
        summary=(f"{n} private cards each.",
                 f"Flop: rows of {flop_txt} cards. {later_turn} {later_river}",
                 *rule_lines, pot_txt),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n),
                Stage("Flop", reveal=tuple(f"flop{i}" for i in range(k)), burn=True),
                Stage("Turn", reveal=("turn",) if turn_shared else tuple(f"turn{i}" for i in range(k)),
                      burn=True),
                Stage("River", reveal=("river",) if river_shared else tuple(f"river{i}" for i in range(k)),
                      burn=key != "twin")),       # Twin Rows: no burn before the river
        board_groups=tuple(groups), rows=tuple(rows), max_players=10)


# ---------------------------------------------------------------- Pyramid
def build_pyramid_family(o):
    n = int(o["private"])
    use = _use(o["rule"], n, 5)
    tiers = [("t5", "Row of 5", 5, 4), ("t4", "Row of 4", 4, 3), ("t3", "Row of 3", 3, 2),
             ("t2", "Row of 2", 2, 1), ("t1", "Top card", 1, 0)]
    return Variant(
        id="pyramid", name="Pyramid", options=_opts(o), selection="declare",
        summary=(f"{n} private cards each. Pyramid of 15 community cards: rows of 5, 4, 3, 2, 1.",
                 "Flop reveals the rows of 5, 4 and 3; turn the row of 2; river the top card.",
                 "Your community cards: at most one from each pyramid row.",
                 f"Hand: {rule_text(use, n)}.",
                 "At showdown YOU pick your cards — a weaker pick counts. Bots pick their best."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n),
                Stage("Flop", reveal=("t5", "t4", "t3"), burn=True),
                Stage("Turn", reveal=("t2",), burn=True), Stage("River", reveal=("t1",), burn=True)),
        board_groups=tuple(BoardGroup(g, label, size, row=row) for g, label, size, row in tiers),
        rows=(HandRow("main", "Pyramid", ("t5", "t4", "t3", "t2", "t1"), use,
                      one_per_group=True),), max_players=10)


# ---------------------------------------------------------------- Personal board
def build_personal(o):
    n = int(o["private"])
    total = n + 2
    use = tuple(k for k in range(0, min(total, 5) + 1) if 5 - k <= 3)
    return Variant(
        id="personal", name="Personal board", options=_opts(o),
        summary=(f"{n} private cards each (face down).",
                 "Flop: 3 community cards shared by everyone.",
                 "Turn and river: each player gets their OWN card, dealt face up — everyone "
                 "can see it, only its owner can use it.",
                 "Hand: best 5 from your private cards, your own turn and river cards, and the flop."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n), Stage("Flop", reveal=("flop",), burn=True),
                Stage("Turn", hole_cards=1, hole_up=True, burn=True),
                Stage("River", hole_cards=1, hole_up=True, burn=True)),
        board_groups=(BoardGroup("flop", "Flop", 3),),
        rows=(HandRow("main", "Hand", ("flop",), use),), max_players=10)


# ---------------------------------------------------------------- Poker Patti
def build_poker_patti(o):
    omaha = o["style"] == "omaha"
    p_cards = 4 if omaha else 2
    n = p_cards + 3
    use = (2,) if omaha else (0, 1, 2)
    return Variant(
        id="poker_patti", name="Poker Patti" + (" · Omaha" if omaha else " · Texas"),
        options=_opts(o), scoring="split",
        summary=(f"{n} private cards each; 5 community cards (flop 3, turn 1, river 1).",
                 f"Before showdown split your cards: {p_cards} for POKER, 3 for TEEN PATTI.",
                 f"Poker: {rule_text(use, p_cards)} with the community cards.",
                 "Teen Patti: your 3 cards alone. Trail > Pure sequence > Sequence > Color > "
                 "Pair > High card (A-K-Q is the top sequence, A-2-3 next).",
                 "Pot split half for poker, half for Teen Patti."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n), Stage("Flop", reveal=("flop",), burn=True),
                Stage("Turn", reveal=("turn",), burn=True), Stage("River", reveal=("river",), burn=True)),
        board_groups=(BoardGroup("flop", "Flop", 3, col=0), BoardGroup("turn", "Turn", 1, col=1),
                      BoardGroup("river", "River", 1, col=2)),
        rows=(HandRow("poker", "Poker", ("flop", "turn", "river"), use, p_cards),
              HandRow("patti", "Teen Patti", (), (3,), 3, kind="teen_patti")),
        max_players=6)


# ---------------------------------------------------------------- Elevator floors
def build_floors(o):
    """Floors of 1, 2 and 3 flop cards sharing one turn and river. The low
    floors come with free jokers: floor 1 has 2, floor 2 has 1, floor 3 none,
    so every floor has 5 community items. 6 private cards, split into 3 pairs
    at showdown (one pair per floor); a showdown on each floor, pot in thirds.
    (Agreed with the owner 2026-11-10: this is the only way to play it.)"""
    groups = [BoardGroup(f"f{i}", f"Floor {i}", i, row=i - 1, col=0) for i in (1, 2, 3)]
    groups += [BoardGroup("turn", "Turn (shared)", 1, row=0, col=1, row_span=3),
               BoardGroup("river", "River (shared)", 1, row=0, col=2, row_span=3)]
    rows = []
    for i in (1, 2, 3):
        j = 3 - i
        tag = f" (+{j} joker{'s' if j > 1 else ''})" if j else ""
        rows.append(HandRow(f"f{i}", f"Floor {i}{tag}", (f"f{i}", "turn", "river"), (2,), 2,
                            jokers=j))
    return Variant(
        id="floors", name="Elevator floors", options=_opts(o), scoring="split",
        summary=("6 private cards each.",
                 "Flop: three floors of 1, 2 and 3 cards. Turn and river: 1 card each, "
                 "shared by every floor.",
                 "Free jokers: floor 1 gets 2 jokers, floor 2 gets 1 joker, floor 3 none. "
                 "A joker can be any card (no five of a kind).",
                 "At showdown split your 6 cards into 3 pairs: one pair per floor. Each floor: "
                 "your pair + 3 of that floor's cards, the turn, the river and its jokers "
                 "(jokers always play) — 5 cards in all.",
                 "Pot split in thirds: a showdown on each floor."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=6),
                Stage("Flop", reveal=("f1", "f2", "f3"), burn=True),
                Stage("Turn", reveal=("turn",), burn=True),
                Stage("River", reveal=("river",), burn=True)),
        board_groups=tuple(groups), rows=tuple(rows), max_players=6)


# ---------------------------------------------------------------- Tic-tac-toe
TTT_LINES = (
    ("row1", "Top row", ("c00", "c01", "c02")), ("row2", "Middle row", ("c10", "c11", "c12")),
    ("row3", "Bottom row", ("c20", "c21", "c22")),
    ("col1", "Left column", ("c00", "c10", "c20")), ("col2", "Middle column", ("c01", "c11", "c21")),
    ("col3", "Right column", ("c02", "c12", "c22")),
    ("diag1", "Diagonal ↘", ("c00", "c11", "c22")), ("diag2", "Diagonal ↙", ("c02", "c11", "c20")),
)


def build_tictactoe(o):
    """A 3x3 grid: corners at the flop, edges at the turn, centre at the river.
    A hand is exactly 2 private cards + the 3 cards of one line."""
    n = int(o["private"])
    groups = tuple(BoardGroup(f"c{r}{c}", f"Row {r + 1}, column {c + 1}", 1, row=r, col=c)
                   for r in range(3) for c in range(3))
    rows = tuple(HandRow(rid, label, cells, (2,)) for rid, label, cells in TTT_LINES)
    return Variant(
        id="tictactoe", name="Tic-tac-toe", options=_opts(o), scoring="best",
        summary=(f"{n} private cards each. 9 community cards in a 3×3 grid.",
                 "Flop: the 4 corners. Turn: the 4 edges. River: the centre.",
                 f"Hand: exactly 2 of your private cards + the 3 cards of ONE line — a row, "
                 "a column or a diagonal (8 lines).",
                 "Single pot: claim one line; the best claim wins it all."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n),
                Stage("Flop", reveal=("c00", "c02", "c20", "c22"), burn=True),
                Stage("Turn", reveal=("c01", "c10", "c12", "c21"), burn=True),
                Stage("River", reveal=("c11",), burn=True)),
        board_groups=groups, rows=rows, max_players=10)


# ---------------------------------------------------------------- Hold'em-shaped boards
CLASSIC_STAGES = (Stage("Flop", reveal=("flop",), burn=True),
                  Stage("Turn", reveal=("turn",), burn=True),
                  Stage("River", reveal=("river",), burn=True))
CLASSIC_GROUPS = (BoardGroup("flop", "Flop", 3, col=0), BoardGroup("turn", "Turn", 1, col=1),
                  BoardGroup("river", "River", 1, col=2))
SHORT_36 = tuple(c for c in STANDARD_52 if repr(c)[0] not in "2345")
ROYAL_20 = tuple(c for c in STANDARD_52 if repr(c)[0] in "TJQKA")
RED_RIVERS = 6                    # extra rivers available (the chain stops at a black card)


def build_red_river(o):
    n, rule = int(o["private"]), o["rule"]
    extra = [BoardGroup(f"river{k}", f"River {k}", 1, row=1, col=k - 2, optional=True)
             for k in range(2, RED_RIVERS + 2)]
    use = _use(rule, n, 5)
    return Variant(
        id="redriver", name="Red River" + ("" if n == 2 else f" · {n} cards"),
        options=_opts(o), red_river=RED_RIVERS,
        summary=(f"{n} private cards each; flop, turn and river as in Hold'em.",
                 "If the river is RED (♥ ♦), another river is dealt and there's another round "
                 "of betting — again and again until a BLACK river (♠ ♣) ends it "
                 f"(at most {RED_RIVERS} extra rivers).",
                 f"Hand: best 5 from your cards and the whole board ({rule_text(use, n)})."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n),) + CLASSIC_STAGES + tuple(
            Stage(f"River {k}", reveal=(f"river{k}",), burn=True) for k in range(2, RED_RIVERS + 2)),
        board_groups=CLASSIC_GROUPS + tuple(extra),
        rows=(HandRow("main", "Board", ("flop", "turn", "river") + tuple(g.id for g in extra),
                      use),), max_players=10)


def build_short_deck(o):
    n, rule = int(o["private"]), o["rule"]
    use = _use(rule, n, 5)
    return Variant(
        id="shortdeck", name="Short Deck (6+)" + ("" if n == 2 else f" · {n} cards"),
        options=_opts(o),
        summary=("36-card deck: the 2s, 3s, 4s and 5s are removed.",
                 f"{n} private cards each; flop, turn and river as in Hold'em.",
                 "A FLUSH BEATS A FULL HOUSE (flushes are rarer here). A-6-7-8-9 is a straight.",
                 f"Hand: {rule_text(use, n)}."),
        deck=SHORT_36, stages=(Stage("Preflop", hole_cards=n),) + CLASSIC_STAGES,
        board_groups=CLASSIC_GROUPS,
        rows=(HandRow("main", "Board", ("flop", "turn", "river"), use, kind="short"),),
        max_players=6)


def build_royal(o):
    return Variant(
        id="royal", name="Royal Hold'em", options=_opts(o),
        summary=("Only the 10s, Jacks, Queens, Kings and Aces: 20 cards.",
                 "2 private cards each; flop, turn and river as in Hold'em.",
                 "Big hands everywhere: the only straight is A-K-Q-J-10, and any flush is a "
                 "royal flush.",
                 "Hand: best 5 from your 2 cards and the board."),
        deck=ROYAL_20, stages=(Stage("Preflop", hole_cards=2),) + CLASSIC_STAGES,
        board_groups=CLASSIC_GROUPS,
        rows=(HandRow("main", "Board", ("flop", "turn", "river"), (0, 1, 2)),), max_players=6)


def build_courchevel(o):
    return Variant(
        id="courchevel", name="Courchevel", options=_opts(o),
        summary=("Omaha with 5 private cards each.",
                 "The first flop card is turned up BEFORE the preflop betting.",
                 "Then the other 2 flop cards, the turn and the river as usual.",
                 "Hand: exactly 2 of your private cards + 3 community cards."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=5, reveal=("flop1",)),
                Stage("Flop", reveal=("flop2",), burn=True),
                Stage("Turn", reveal=("turn",), burn=True),
                Stage("River", reveal=("river",), burn=True)),
        board_groups=(BoardGroup("flop1", "First flop card", 1, col=0),
                      BoardGroup("flop2", "Flop", 2, col=1),
                      BoardGroup("turn", "Turn", 1, col=2), BoardGroup("river", "River", 1, col=3)),
        rows=(HandRow("main", "Board", ("flop1", "flop2", "turn", "river"), (2,)),),
        max_players=8)


def build_hilo(o):
    n = int(o["private"])
    return Variant(
        id="hilo", name="Omaha Hi-Lo" + ("" if n == 4 else f" · {n} cards"),
        options=_opts(o), scoring="split",
        summary=(f"{n} private cards each; 5 community cards (flop, turn, river).",
                 "Pot split in half: the best HIGH hand, and the best LOW hand.",
                 "Low: 5 different cards of 8 or lower (Ace counts low; straights and flushes "
                 "don't hurt). A-2-3-4-5 is the best low. No low? The high hand takes it all.",
                 "Each hand (high and low): exactly 2 of your private cards + 3 community cards; "
                 "you may use different cards for each."),
        deck=STANDARD_52, stages=(Stage("Preflop", hole_cards=n),) + CLASSIC_STAGES,
        board_groups=CLASSIC_GROUPS,
        rows=(HandRow("high", "High", ("flop", "turn", "river"), (2,)),
              HandRow("low", "Low", ("flop", "turn", "river"), (2,), kind="low8")),
        max_players=8)


# ---------------------------------------------------------------- shaped boards
def build_iron_cross(o):
    n = int(o["private"])
    groups = (BoardGroup("top", "Top", 1, row=0, col=1), BoardGroup("left", "Left", 1, row=1, col=0),
              BoardGroup("centre", "Centre", 1, row=1, col=1),
              BoardGroup("right", "Right", 1, row=1, col=2),
              BoardGroup("bottom", "Bottom", 1, row=2, col=1))
    use = tuple(range(2, min(n, 5) + 1))
    return Variant(
        id="ironcross", name="Iron Cross", options=_opts(o), scoring="best",
        summary=(f"{n} private cards each. 5 community cards in a + shape.",
                 "Flop: the left and right cards. Turn: top and bottom. River: the centre.",
                 f"Hand: your private cards + EITHER the row (left-centre-right) OR the column "
                 f"(top-centre-bottom) — {rule_text(use, n)}.",
                 "Single pot: claim the row or the column; the best claim wins."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n), Stage("Flop", reveal=("left", "right"), burn=True),
                Stage("Turn", reveal=("top", "bottom"), burn=True),
                Stage("River", reveal=("centre",), burn=True)),
        board_groups=groups,
        rows=(HandRow("across", "Row", ("left", "centre", "right"), use),
              HandRow("down", "Column", ("top", "centre", "bottom"), use)), max_players=9)


def build_chowaha(o):
    n = int(o["private"])
    groups = (BoardGroup("f1", "Flop 1", 3, row=0, col=0, row_span=2),
              BoardGroup("f2", "Flop 2", 3, row=2, col=0, row_span=2),
              BoardGroup("f3", "Flop 3", 3, row=4, col=0, row_span=2),
              BoardGroup("t1", "Turn 1", 1, row=1, col=1, row_span=2),
              BoardGroup("t2", "Turn 2", 1, row=3, col=1, row_span=2),
              BoardGroup("river", "River", 1, row=2, col=2, row_span=2))
    paths = (("p1", "Flop 1 → Turn 1", ("f1", "t1", "river")),
             ("p2", "Flop 2 → Turn 1", ("f2", "t1", "river")),
             ("p3", "Flop 2 → Turn 2", ("f2", "t2", "river")),
             ("p4", "Flop 3 → Turn 2", ("f3", "t2", "river")))
    return Variant(
        id="chowaha", name="Chowaha" + ("" if n == 2 else f" · {n} cards"),
        options=_opts(o), scoring="best",
        summary=(f"{n} private cards each.",
                 "Flop: three flops of 3 cards, stacked. Turn: two turn cards — the top one "
                 "touches flops 1 and 2, the bottom one flops 2 and 3. River: one card touching both turns.",
                 "Hand: exactly 2 of your private cards + 3 community cards from ONE connected "
                 "path: a flop → a turn it touches → the river.",
                 "Single pot: claim one path; the best claim wins."),
        deck=STANDARD_52,
        stages=(Stage("Preflop", hole_cards=n), Stage("Flop", reveal=("f1", "f2", "f3"), burn=True),
                Stage("Turn", reveal=("t1", "t2"), burn=True),
                Stage("River", reveal=("river",), burn=True)),
        board_groups=groups,
        rows=tuple(HandRow(pid, label, gids, (2,)) for pid, label, gids in paths), max_players=10)


# ---------------------------------------------------------------- new mechanics
def build_blackjack(o):
    return Variant(
        id="blackjack", name="Blackjack Hold'em", options=_opts(o), scoring="split",
        blackjack=True,
        summary=("2 private cards each; flop, turn and river as in Hold'em.",
                 "After the flop is dealt (before its betting), each player in turn may HIT "
                 "(take another private card, face down) as often as they like, or STAND.",
                 "Blackjack count: 2-10 as shown, J Q K = 10, Ace = 1 or 11. Over 21 = BUST: "
                 "you're out of the hand.",
                 "Pot split in half: the best POKER hand (any 2 of your cards + the board), and "
                 "the total CLOSEST TO 21 without going over (a tie goes to the better poker hand).",
                 "A-K is a monster: it's 21 already AND a great Hold'em hand."),
        deck=STANDARD_52, stages=(Stage("Preflop", hole_cards=2),) + CLASSIC_STAGES,
        board_groups=CLASSIC_GROUPS,
        rows=(HandRow("poker", "Poker", ("flop", "turn", "river"), (0, 1, 2)),
              HandRow("bj", "21", (), (0,), kind="bj21")), max_players=8)


def build_wall_street(o):
    size = int(o["market"])
    return Variant(
        id="wallstreet", name="Wall Street", options=_opts(o), market=(size, 3),
        summary=("3 private cards each.",
                 f"The MARKET: {size} investment cards face up, each with a price: 2-9 cost 1 big "
                 "blind, 10-K cost 2, an Ace costs 3. Prices go into the pot.",
                 "Starting left of the dealer, each player in turn BUYS one card or FOLDS. A "
                 "bought card is replaced from the deck at once. Keep going until everyone has "
                 "bought 3 cards (or folded).",
                 "Bought cards are face up — everyone sees your investments.",
                 "Then one round of betting. Hand: best 5 from your 3 private + 3 bought cards."),
        deck=STANDARD_52, stages=(Stage("Preflop", hole_cards=3),), board_groups=(),
        rows=(HandRow("main", "Hand", (), (5,)),), max_players=8)


FAMILIES: dict[str, Preset] = {p.id: p for p in (
    Preset("classic", "Classic board", "5 community cards · Hold'em, Omaha and more",
           (PRIVATE((2, 3, 4, 5, 6), 2), RULE3), build_classic),
    Preset("double", "Double board", "2 separate boards · pot split per board",
           (PRIVATE((4, 6, 8), 4),
            Option("cards", "Private cards across boards",
                   (("split", "Split between boards"), ("shared", "Use on both boards")), "split"),
            RULE3), build_double),
    Preset("rows", "Shared-card rows", "Rows sharing a turn/river · 2or3, 3or3or2, Elevator…",
           (Option("layout", "Layout",
                   (("2or3", "3+2 · shared turn"), ("2or3r", "3+2 · shared river"),
                    ("3or3or2", "3+3+2 · shared turn"), ("twin", "3+3 · shared turn"),
                    ("elevator", "3+3+3 · shared turn & river")), "2or3"),
            Option("private", "Private cards",
                   (("classic", "Classic"),) + tuple((str(v), str(v)) for v in (3, 4, 5, 6, 7)),
                   "classic"),
            Option("rule", "Hand rule",
                   (("classic", "Classic"), ("fixed", "5 shown→2, 4 shown→3"),
                    ("any", "Any 5 cards"), ("fix2", "Fix 2")), "classic"),
            Option("pot", "Pot", (("classic", "Classic"), ("best", "Best row wins all"),
                                  ("split", "Split cards, pot per row")), "classic")),
           build_rows),
    Preset("pyramid", "Pyramid", "15-card pyramid · you pick one per row",
           (PRIVATE((2, 3, 4), 2),
            Option("rule", "Hand rule", (("any", "Any 5 cards"), ("fix2", "Fix 2 from hand")), "any")),
           build_pyramid_family),
    Preset("personal", "Personal board", "Common flop · your own face-up turn & river",
           (PRIVATE((2, 3, 4, 5), 2),), build_personal),
    Preset("poker_patti", "Poker Patti", "2 cards for poker + 3 for Teen Patti",
           (Option("style", "Poker part", (("texas", "Texas (2 cards)"), ("omaha", "Omaha (4 cards, Fix 2)")),
                   "texas"),), build_poker_patti),
    Preset("floors", "Elevator floors", "Floors of 1+2+3 · 6 cards, a pair per floor, pot in thirds",
           (), build_floors),
    Preset("tictactoe", "Tic-tac-toe", "3×3 grid · claim a row, column or diagonal",
           (PRIVATE((2, 3, 4), 4),), build_tictactoe),
    Preset("redriver", "Red River", "A red river? Another river + more betting",
           (PRIVATE((2, 4), 2),
            Option("rule", "Hand rule", (("any", "Any 5 cards"), ("fix2", "Fix 2 (Omaha)")), "any")),
           build_red_river),
    Preset("hilo", "Omaha Hi-Lo", "Pot split: best high + best low (8 or better)",
           (PRIVATE((4, 5), 4),), build_hilo),
    Preset("courchevel", "Courchevel", "Omaha, 5 cards · one flop card shown before betting",
           (), build_courchevel),
    Preset("ironcross", "Iron Cross", "+ shaped board · claim the row or the column",
           (PRIVATE((4, 5), 4),), build_iron_cross),
    Preset("chowaha", "Chowaha", "3 flops → 2 turns → 1 river · claim a path",
           (PRIVATE((2, 4), 2),), build_chowaha),
    Preset("blackjack", "Blackjack Hold'em", "Poker + get closest to 21 · half pot each",
           (), build_blackjack),
    Preset("wallstreet", "Wall Street", "Buy investment cards from the market",
           (Option("market", "Market size", (("3", "3 cards"), ("4", "4 cards"), ("5", "5 cards")), "4"),),
           build_wall_street),
)}
