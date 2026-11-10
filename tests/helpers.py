"""Deterministic fixtures: build a shoe that deals exactly the cards we want."""
from engine.cards import STANDARD_52, Shoe, parse_cards


def stacked_variant(variant, holes: list[str], board: dict[str, str]) -> Shoe:
    """Shoe for any variation. ``holes[i]`` = PokerKit player i's private
    cards (dealt one at a time, round-robin); ``board[group_id]`` = that
    group's cards. Burns and unspecified cards come from the rest of the deck."""
    from engine.evaluate import parse_one

    def cards(text):                     # 2 characters per card; "X1"/"X2" = jokers
        return [parse_one(text[i:i + 2]) for i in range(0, len(text), 2)]

    hole_cards = [cards(h) for h in holes]
    board_cards = {g: cards(c) for g, c in board.items()}
    used = [c for h in hole_cards for c in h] + [c for cs in board_cards.values() for c in cs]
    assert len(set(used)) == len(used), "duplicate in fixture"
    filler = iter([c for c in variant.deck if c not in set(used)])
    order, k = [], 0
    for stage in variant.stages:
        if stage.burn:
            order.append(next(filler))
        for _ in range(stage.hole_cards):          # (PokerKit: hole cards before the board)
            for h in hole_cards:
                order.append(h[k] if k < len(h) else next(filler))
            k += 1
        for gid in stage.reveal:
            want = list(board_cards.get(gid, []))
            for _ in range(variant.group(gid).size):
                order.append(want.pop(0) if want else next(filler))
    order.extend(filler)
    return Shoe.stacked(order)


def stacked_holdem(holes: list[str], board: str = "") -> Shoe:
    """``holes[i]`` = the two cards for PokerKit player i (i=0 is first seat
    left of the button, last is the button). Cards are dealt one at a time
    round-robin, then burn/flop/burn/turn/burn/river. Unused positions are
    filled with the remaining deck so nothing runs out."""
    hole_cards = [parse_cards(h) for h in holes]
    board_cards = parse_cards(board)
    used = {c for h in hole_cards for c in h} | set(board_cards)
    assert len(used) == sum(map(len, hole_cards)) + len(board_cards), "duplicate in fixture"
    filler = iter([c for c in STANDARD_52 if c not in used])
    order = []
    for k in range(2):
        for h in hole_cards:
            order.append(h[k])
    b = iter(board_cards)
    for count in (3, 1, 1):
        order.append(next(filler))                 # burn
        for _ in range(count):
            order.append(next(b, None) or next(filler))
    order.extend(filler)
    return Shoe.stacked(order)
