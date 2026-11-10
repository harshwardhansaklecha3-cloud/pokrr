"""Probe 4: let PokerKit do betting + pots + payouts while WE decide hand
strength. Uses per-hand dynamic Hand classes ("portions"). Checks:
- 3 portions -> each pot split in thirds, odd chips handled
- one player winning all portions takes everything
- a folded player is never paid
"""
import warnings

import pokerkit as pk
from pokerkit import Automation as A

warnings.simplefilter("error")
AUTO = (A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING,
        A.RUNOUT_COUNT_SELECTION, A.CHIPS_PULLING)


def portion_types(scores, n):
    """scores: {frozenset(hole): [hand_for_portion0, hand_for_portion1, ...]}"""
    types = []
    for k in range(n):
        class Portion(pk.StandardHighHand):
            @classmethod
            def from_game(cls, hole_cards, board_cards=(), _k=k):
                key = frozenset(pk.Card.clean(hole_cards))
                if key not in scores:
                    raise ValueError("no declared hand")
                return scores[key][_k]
        types.append(Portion)
    return tuple(types)


def run(label, n, wins, stacks=(1000, 1000, 1000), fold_p2=False, sb=5, bb=10):
    holes = ["AhAd", "KhKd", "QhQd"]
    H = pk.StandardHighHand
    strong, mid, weak = H("AsAcKsKcQs"), H("9s9c8s8c2d"), H("7s5c4d3h2s")
    scores = {}
    for i, h in enumerate(holes):
        scores[frozenset(pk.Card.clean(h))] = [
            {0: strong, 1: mid, 2: weak}[wins[k].index(i)] for k in range(n)]
    streets = (pk.Street(False, (False, False), 0, False, pk.Opening.POSITION, bb, None),
               pk.Street(False, (), 5, False, pk.Opening.POSITION, bb, None))
    st = pk.State(AUTO, pk.Deck.STANDARD, portion_types(scores, n), streets,
                  pk.BettingStructure.NO_LIMIT, True, 0, (sb, bb), 0, stacks, 3)
    for h in holes:
        st.deal_hole(h)
    st.complete_bet_or_raise_to(101)   # P2 raises to 101
    if fold_p2:
        st.check_or_call(); st.check_or_call()
    else:
        st.check_or_call(); st.check_or_call()
    st.deal_board("2c3c4c5c7d")
    if fold_p2:
        st.check_or_call(); st.complete_bet_or_raise_to(50); st.check_or_call(); st.fold()
    else:
        while st.actor_index is not None:
            st.check_or_call()
    pushes = []
    while st.status:
        if st.can_show_or_muck_hole_cards():
            st.show_or_muck_hole_cards(True)
        elif st.can_kill_hand():
            st.kill_hand()
        elif st.can_push_chips():
            p = st.push_chips()
            pushes.append((p.pot_index, p.hand_type_index, p.amounts))
        elif st.can_no_operate():
            st.no_operate()
        else:
            raise SystemExit("stuck")
    print(f"--- {label}")
    for p in pushes:
        print("   pot", p[0], "portion", p[1], "->", p[2])
    print("   stacks", st.stacks, "sum", sum(st.stacks))


# wins[k] = ranking of players for portion k (best first)
run("3 portions, 3 different winners (pot 303 -> 101 each)", 3,
    [[0, 1, 2], [1, 0, 2], [2, 0, 1]])
run("3 portions, same winner", 3, [[0, 1, 2]] * 3)
run("1 portion (best-row-wins), P1 best", 1, [[1, 0, 2]])
run("3 portions, odd pot (blinds 5/10, extra 5 dead)", 3,
    [[0, 1, 2], [1, 0, 2], [2, 0, 1]], stacks=(1000, 1000, 1000), sb=7, bb=10)
run("P2 folds on flop despite 'best' portion 2", 3,
    [[0, 1, 2], [1, 0, 2], [2, 0, 1]], fold_p2=True)
