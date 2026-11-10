"""Probe 3: does PokerKit support double-board games natively?

Checks starting_board_count=2: are the two boards dealt different cards,
and is each pot split per board (scoop if one player wins both)?
"""
import warnings

import pokerkit as pk
from pokerkit import Automation as A

warnings.simplefilter("error")
AUTO = (A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING,
        A.RUNOUT_COUNT_SELECTION, A.CHIPS_PULLING)


def run(hand_type, holes, boards, label):
    n_hole = len(holes[0]) // 2
    streets = (
        pk.Street(False, (False,) * n_hole, 0, False, pk.Opening.POSITION, 10, None),
        pk.Street(False, (), 3, False, pk.Opening.POSITION, 10, None),
        pk.Street(False, (), 1, False, pk.Opening.POSITION, 10, None),
        pk.Street(False, (), 1, False, pk.Opening.POSITION, 10, None),
    )
    st = pk.State(AUTO, pk.Deck.STANDARD, (hand_type,), streets,
                  pk.BettingStructure.NO_LIMIT, True, 0, (5, 10), 0,
                  (1000, 1000, 1000), 3, starting_board_count=2)
    for h in holes:
        st.deal_hole(h)
    print(f"\n--- {label} --- board_count={st.board_count}")
    st.complete_bet_or_raise_to(100); st.check_or_call(); st.check_or_call()
    # boards[0] and boards[1] are 5 cards each. Feed flop/turn/river.
    cuts = [(0, 3), (3, 4), (4, 5)]
    log = []
    while st.status:
        if st.actor_index is not None:
            st.check_or_call(); continue
        if st.can_deal_board():
            a, b = cuts.pop(0)
            # One deal_board call per board? Or one call with all cards?
            needed = st.board_dealing_count
            log.append(f"deal_board needs {needed} card(s) per call")
            st.deal_board(boards[0][a * 2:b * 2])
            if st.can_deal_board() and st.board_dealing_count:
                st.deal_board(boards[1][a * 2:b * 2])
        elif st.can_show_or_muck_hole_cards():
            st.show_or_muck_hole_cards(True)
        elif st.can_kill_hand():
            st.kill_hand()
        elif st.can_push_chips():
            p = st.push_chips()
            log.append(f"push pot {p.pot_index} board {p.board_index}: {p.amounts}")
        elif st.can_no_operate():
            st.no_operate()
        else:
            raise SystemExit("stuck")
    for line in log:
        print(" ", line)
    print("  board 0:", list(st.get_board_cards(0)))
    print("  board 1:", list(st.get_board_cards(1)))
    print("  final stacks:", st.stacks, "sum", sum(st.stacks))


# Hold'em hand rule (any 5 of 7) with 2 hole cards each:
# P0 wins board 0 (aces), P1 wins board 1 (kings), P2 loses both.
run(pk.StandardHighHand, ["AhAd", "KhKd", "7c2d"],
    ["As8c4d9hJs", "Ks8d3c9cQs"], "Hold'em rules, different winners per board")
# P0 scoops both boards.
run(pk.StandardHighHand, ["AhAd", "KhKd", "7c2d"],
    ["As8c4d9hJs", "Ac8d3c9cQs"], "Hold'em rules, same winner both boards")
# Omaha rule (exactly 2 of 4 hole + 3 board) with 4 hole cards.
run(pk.OmahaHoldemHand, ["AhAdQcQd", "KhKd2s3s", "7c2d5h6h"],
    ["As8c4d9hJs", "Ks8d3c9cTs"], "Omaha rules, 4 hole cards, double board")
