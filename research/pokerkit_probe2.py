"""Second probe: heads-up blinds, manual burn/show/push, operation records."""
import inspect
import warnings

import pokerkit as pk
from pokerkit import Automation as A

warnings.simplefilter("error")  # any PokerKit warning becomes an exception

AUTO = (A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING,
        A.RUNOUT_COUNT_SELECTION, A.HAND_KILLING, A.CHIPS_PULLING)

print("no_operate doc:", (pk.State.no_operate.__doc__ or "").strip()[:120])
print("ChipsPushing fields:", inspect.signature(pk.state.ChipsPushing))

print("\n--- heads-up ---")
s = pk.NoLimitTexasHoldem.create_state(AUTO, True, 0, (1, 2), 2, (100, 100), 2)
print("bets after blinds:", s.bets)
s.deal_hole("AsKs"); s.deal_hole("2c2d")  # each call deals one player's cards
print("first preflop actor:", s.actor_index)
s.check_or_call(); s.check_or_call()
print("can burn?", s.can_burn_card(), "board count to deal", s.board_dealing_count)
s.burn_card("3c"); s.deal_board("7c8d9h")
print("first postflop actor:", s.actor_index)

print("\n--- full hand, manual everything after betting ---")
s = pk.NoLimitTexasHoldem.create_state(AUTO, True, 0, (1, 2), 2, (50, 100, 100), 3)
for c in ("AhAd", "KhKd", "QcQd"):
    pass
cards = iter(["Ah", "Kh", "Qc", "Ad", "Kd", "Qd"])
while s.can_deal_hole():
    s.deal_hole(next(cards))
print("hole:", s.hole_cards)
s.complete_bet_or_raise_to(100); s.check_or_call(); s.check_or_call()
board = iter(["2s", "7h", "8c", "9d", "3s", "4c", "Js", "5h"])
log = []
while s.status:
    if s.actor_index is not None:
        raise SystemExit("unexpected actor")
    if s.can_burn_card():
        log.append(s.burn_card(next(board)))
    elif s.can_deal_board():
        n = s.board_dealing_count
        log.append(s.deal_board("".join(next(board) for _ in range(n))))
    elif s.can_show_or_muck_hole_cards():
        log.append(s.show_or_muck_hole_cards(True))
    elif s.can_push_chips():
        log.append(s.push_chips())
    elif s.can_no_operate():
        log.append(s.no_operate())
    else:
        raise SystemExit("stuck")
for op in log:
    print(" ", op)
print("stacks", s.stacks, "board", list(s.get_board_cards(0)))
print("hand P0:", s.get_hand(0, 0, 0), "| label:", s.get_hand(0, 0, 0).entry.label)
