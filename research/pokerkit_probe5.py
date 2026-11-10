"""Probe: what the new variations need from PokerKit 0.7.7.
- short-deck and 8-or-better low hand classes
- a betting street that deals nothing (Dice round)
- a board card dealt on the first street (Courchevel)
- hi/lo pot when nobody has a low
"""
import pokerkit as pk
from pokerkit import Automation as A

print("ShortDeck:", pk.ShortDeckHoldemHand("Ah6s7d8c9h").entry.label)
print("SD flush vs full:", pk.ShortDeckHoldemHand("AhKhQh9h7h") > pk.ShortDeckHoldemHand("KsKdKc7s7d"))
print("SD trips vs straight:", pk.ShortDeckHoldemHand("KsKdKc7s8d") > pk.ShortDeckHoldemHand("Ah6s7d8c9h"))
try:
    print("low:", pk.EightOrBetterLowHand("As2d3c4h8s").entry.label)
    pk.EightOrBetterLowHand("As2d3c4h9s")
    print("9 low accepted?!")
except ValueError as e:
    print("9 low refused:", e)
print("low order:", pk.EightOrBetterLowHand("As2d3c4h5s") > pk.EightOrBetterLowHand("As2d3c4h8s"))

AUTO = (A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING, A.RUNOUT_COUNT_SELECTION,
        A.CHIPS_PULLING, A.CARD_BURNING, A.HOLE_DEALING, A.BOARD_DEALING, A.HOLE_CARDS_SHOWING_OR_MUCKING,
        A.HAND_KILLING, A.CHIPS_PUSHING)


def street(burn, hole, board):
    return pk.Street(burn, (False,) * hole, board, False, pk.Opening.POSITION, 2, None)


# Courchevel-ish first street with a board card, + a no-deal betting street
st = pk.State(AUTO, pk.Deck.STANDARD, (pk.StandardHighHand,),
              (street(False, 2, 1), street(True, 0, 2), street(False, 0, 1)),  # dice street: deals the replacement card
              pk.BettingStructure.NO_LIMIT, True, 0, (1, 2), 0, (100, 100), 2)
print("board after first street deal:", st.board_cards, "street", st.street_index)
while st.status:
    if st.actor_index is not None:
        st.check_or_call()
print("finished ok with a no-deal street; board", st.board_cards)

# hi/lo where nobody qualifies low
st = pk.State(AUTO[:5], pk.Deck.STANDARD, (pk.StandardHighHand, pk.EightOrBetterLowHand),
              (street(False, 2, 0), street(True, 0, 5)),
              pk.BettingStructure.NO_LIMIT, True, 0, (1, 2), 0, (100, 100), 2)
cards = iter(pk.Card.parse("KsKd QsQd 9c Th Jc 9h Tc Js"))
while st.status:
    if st.can_deal_hole():
        st.deal_hole(next(cards))
    elif st.can_burn_card():
        st.burn_card(next(iter(pk.Card.parse("2c"))))
    elif st.can_deal_board():
        st.deal_board([next(cards) for _ in range(st.board_dealing_count)])
    elif st.actor_index is not None:
        st.check_or_call()
    elif st.can_show_or_muck_hole_cards():
        st.show_or_muck_hole_cards(True)
    elif st.can_kill_hand():
        st.kill_hand()
    elif st.can_push_chips():
        print("push:", st.push_chips())
    elif st.can_no_operate():
        st.no_operate()
    else:
        break
print("stacks after no-low hand:", st.stacks)
