"""Small runnable experiments that verify PokerKit behaviour we rely on.

Run:  .venv\\Scripts\\python.exe research\\pokerkit_probe.py
Each section prints what it checks. Nothing here is used by the game itself.
"""
import itertools
import warnings

import pokerkit as pk
from pokerkit import Automation as A, Card

warnings.simplefilter("always")

AUTO = (
    A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING,
    A.CARD_BURNING, A.HOLE_CARDS_SHOWING_OR_MUCKING, A.HAND_KILLING,
    A.CHIPS_PUSHING, A.CHIPS_PULLING,
)  # NOTE: HOLE_DEALING and BOARD_DEALING are NOT automated -> we deal.


def nlhe(stacks, blinds=(1, 2)):
    return pk.NoLimitTexasHoldem.create_state(
        AUTO, True, 0, blinds, blinds[1], stacks, len(stacks))


def section(t):
    print("\n=== " + t + " ===")


section("1. Explicit dealing from our own deck")
s = nlhe((200,) * 3)
print("deck size inside pokerkit:", len(s.deck_cards))
s.deal_hole("AsKs")
print("after dealing AsKs, As still in pokerkit deck?",
      next(Card.parse("As")) in s.deck_cards)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    s.deal_hole("AsQd")  # duplicate As
    print("dealing duplicate As -> warnings:", [str(x.message)[:80] for x in w])

section("2. Blinds, action order, min raise")
s = nlhe((200,) * 6)
deck = [c for c in itertools.islice(pk.Deck.STANDARD, 52)]
i = 0
while s.can_deal_hole():
    s.deal_hole(deck[i:i + 1]); i += 1
print("bets after blinds:", s.bets, "first actor:", s.actor_index)
print("min raise-to:", s.min_completion_betting_or_raising_to_amount,
      "max:", s.max_completion_betting_or_raising_to_amount,
      "call amt:", s.checking_or_calling_amount)
s.complete_bet_or_raise_to(10)  # UTG raises to 10 (raise of 8)
print("after raise to 10, next actor", s.actor_index,
      "min raise-to:", s.min_completion_betting_or_raising_to_amount)
print("can raise to 17 (too small)?", s.can_complete_bet_or_raise_to(17))

section("3. Short all-in does not reopen betting")
# Seats: P0 = small blind, P1 = big blind (short, 30 chips), P2 = button.
s = nlhe((100, 30, 100))
while s.can_deal_hole():
    s.deal_hole(deck[i:i + 1]); i += 1
print("first actor preflop (expect 2 = button):", s.actor_index)
s.complete_bet_or_raise_to(20)          # P2 raises to 20 (raise of 18)
s.check_or_call()                        # P0 calls 20
# P1 shoves to 30 -> raise of 10 < min raise 18 -> incomplete raise
print("P1 max raise-to:", s.max_completion_betting_or_raising_to_amount)
s.complete_bet_or_raise_to(30)
print("after short all-in, actor:", s.actor_index,
      "| can P2 re-raise? (expect False)", s.can_complete_bet_or_raise_to(),
      "| call amt", s.checking_or_calling_amount)

section("4. Side pots + payouts with fixed cards")
# P0 short 50, P1 100, P2 200. P0 has best, P1 second.
s = nlhe((50, 100, 200))
s.deal_hole("AhAd"); s.deal_hole("KhKd"); s.deal_hole("7c2d")
s.complete_bet_or_raise_to(200)   # P2 all in
s.check_or_call()                  # P0 calls all-in 50
s.check_or_call()                  # P1 calls all-in 100
while s.can_deal_board():
    s.deal_board({0: "Ts9s3c", 1: "4h", 2: "5d"}[s.street_index - 1]
                 if False else None) if False else None
    break
print("street", s.street_index, "pots:",
      [(p.amount, tuple(p.player_indices)) for p in s.pots])
for b in ("Ts9s3c", "4h", "5d"):
    if s.can_burn_card():
        s.burn_card("??")
    s.deal_board(b)
print("status", s.status, "final stacks", s.stacks,
      "sum", sum(s.stacks))

section("5. Split pot with odd chip")
s = pk.NoLimitTexasHoldem.create_state(AUTO, True, 1, (1, 2), 2,
                                       (101, 101, 101), 3)  # ante 1 each
s.deal_hole("AhKd"); s.deal_hole("AsKc"); s.deal_hole("2c3d")
# P2 (button) raises to 4, P0 (SB) shoves 100, P1 (BB) calls, P2 folds.
# Pot = 3 antes + 4 + 100 + 100 = 207 -> odd chip. P0 and P1 both have AK.
s.complete_bet_or_raise_to(4); s.complete_bet_or_raise_to(100)
s.check_or_call(); s.fold()
for b in ("QhJhTc", "2s", "3s"):
    s.deal_board(b)
print("stacks", s.stacks, "sum", sum(s.stacks))

section("6. Early win when everyone folds")
s = nlhe((100, 100, 100))
while s.can_deal_hole():
    s.deal_hole(deck[i:i + 1]); i += 1
s.fold(); s.fold()
print("status", s.status, "stacks", s.stacks)

section("7. Board order + custom Hand type (Pyramid-like rows)")


class RowPickHand(pk.StandardHighHand):
    """Prototype: board is 15 cards in rows 5,4,3,2,1; pick 1 per row,
    then best 5 of (2 hole + 5 picked)."""
    ROWS = (5, 4, 3, 2, 1)

    @classmethod
    def from_game(cls, hole_cards, board_cards=()):
        hole = list(pk.Card.clean(hole_cards))
        board = list(pk.Card.clean(board_cards))
        rows, k = [], 0
        for n in cls.ROWS:
            rows.append(board[k:k + n]); k += n
        best = None
        for pick in itertools.product(*rows):
            for combo in itertools.combinations(hole + list(pick), 5):
                h = pk.StandardHighHand(combo)
                best = h if best is None or h > best else best
        if best is None:
            raise ValueError("no hand")
        return cls(best.cards)


st = pk.State(
    AUTO, pk.Deck.STANDARD, (RowPickHand,),
    (pk.Street(False, (False, False), 0, False, pk.Opening.POSITION, 2, None),
     pk.Street(False, (), 12, False, pk.Opening.POSITION, 2, None),
     pk.Street(False, (), 2, False, pk.Opening.POSITION, 2, None),
     pk.Street(False, (), 1, False, pk.Opening.POSITION, 2, None)),
    pk.BettingStructure.NO_LIMIT, True, 0, (1, 2), 0, 100, 2)
st.deal_hole("AsAh"); st.deal_hole("2c7d")
st.check_or_call(); st.check_or_call()
st.deal_board("KsKhKdKc2s" + "3s4s5s6s" + "7s8s9s")
print("board order kept:", "".join(map(repr, st.get_board_cards(0))))
st.check_or_call(); st.check_or_call()
st.deal_board("TdJd"); st.check_or_call(); st.check_or_call()
st.deal_board("Qd"); st.check_or_call(); st.check_or_call()
print("status", st.status, "stacks", st.stacks)
print("P0 hand:", st.get_hand(0, 0, 0), "P1 hand:", st.get_hand(1, 0, 0))

section("8. Evaluator standalone")
h = pk.StandardHighHand.from_game("AsKs", "QsJsTs2c3d")
print(h, "| cards:", h.cards, "| entry label:", h.entry.label)
