import random

import pokerkit as pk
import pytest

from engine.cards import STANDARD_52, DeckExhausted, Shoe, parse_cards
from engine.variants import HOLDEM, BoardGroup, HandRow, Stage, Variant, VariantError


def test_standard_deck_is_52_unique_cards():
    assert len(STANDARD_52) == 52
    assert len(set(STANDARD_52)) == 52
    assert {c.suit for c in STANDARD_52} == set(pk.Suit) - {pk.Suit.UNKNOWN}


def test_shoe_deals_without_duplicates_and_exhausts():
    shoe = Shoe(STANDARD_52, random.Random(7))
    dealt = shoe.draw(52)
    assert len(set(dealt)) == 52
    with pytest.raises(DeckExhausted):
        shoe.draw(1)


def test_seeded_shuffle_is_reproducible_and_default_is_random():
    a = Shoe(STANDARD_52, random.Random(42)).draw(52)
    b = Shoe(STANDARD_52, random.Random(42)).draw(52)
    assert a == b
    c = Shoe(STANDARD_52).draw(52)   # secure shuffle
    d = Shoe(STANDARD_52).draw(52)
    assert c != d   # 1 in 52! chance of a false failure


def test_duplicate_cards_rejected():
    with pytest.raises(ValueError):
        Shoe(parse_cards("AsAsKd"))
    with pytest.raises(ValueError):
        Shoe.stacked(parse_cards("AsKdAs"))


def test_holdem_validates_card_budget():
    HOLDEM.validate(10)                      # 20 + 5 + 3 burns = 28 cards
    with pytest.raises(VariantError):
        HOLDEM.validate(11)                  # over max players
    with pytest.raises(VariantError):
        HOLDEM.validate(1)


ROW_B = (HandRow("main", "Main", ("b",), (2,)),)


def _tiny(deck_size, **kw):
    return Variant(id="tiny", name="Tiny", summary=(), deck=STANDARD_52[:deck_size],
                   stages=(Stage("Pre", hole_cards=2),
                           Stage("Flop", reveal=("b",), burn=True)),
                   board_groups=(BoardGroup("b", "Board", 3),), rows=ROW_B,
                   max_players=9, **kw)


def test_validation_counts_hole_board_and_burn_cards():
    v = _tiny(20)
    v.validate(8)        # 16 + 3 + 1 = 20: exactly enough
    with pytest.raises(VariantError, match="needs 22 cards"):
        v.validate(9)    # 18 + 3 + 1 = 22 > 20


def test_validation_rejects_malformed_definitions():
    with pytest.raises(VariantError):    # board group never revealed
        Variant(id="x", name="x", summary=(), deck=STANDARD_52,
                stages=(Stage("Pre", hole_cards=2),),
                board_groups=(BoardGroup("b", "B", 3),), rows=ROW_B).validate()
    with pytest.raises(VariantError):    # duplicate cards in deck
        Variant(id="x", name="x", summary=(), deck=STANDARD_52 + STANDARD_52[:1],
                stages=(Stage("Pre", hole_cards=2), Stage("F", reveal=("b",))),
                board_groups=(BoardGroup("b", "B", 3),), rows=ROW_B).validate()
    with pytest.raises(VariantError, match="never make a 5-card hand"):
        Variant(id="x", name="x", summary=(), deck=STANDARD_52,     # 2 + 3 board,
                stages=(Stage("Pre", hole_cards=2), Stage("F", reveal=("b",))),
                board_groups=(BoardGroup("b", "B", 3),),            # but must use 1 hole
                rows=(HandRow("m", "M", ("b",), (1,)),)).validate()


@pytest.mark.parametrize("better,worse", [
    ("AsKsQsJsTs", "9h9d9c9s2d"),   # straight flush > quads
    ("9h9d9c9s2d", "KhKdKc2s2d"),   # quads > full house
    ("KhKdKc2s2d", "Ah9h7h5h3h"),   # full house > flush
    ("Ah9h7h5h3h", "6s5d4c3h2s"),   # flush > straight
    ("6s5d4c3h2s", "As5d4c3h2s"),   # 6-high straight > wheel (A-5)
    ("As5d4c3h2s", "QsQdQc9h2s"),   # wheel straight > trips
    ("QsQdQc9h2s", "AsAdKcKh2s"),   # trips > two pair
    ("AsAdKcKh2s", "AsAdKcQh9s"),   # two pair > pair
    ("AsAdKcQh9s", "AsKdQcJh9s"),   # pair > high card
    ("AsKdQcJh9s", "AsKdQcJh8s"),   # kicker
])
def test_hand_ranking_order(better, worse):
    assert pk.StandardHighHand(better) > pk.StandardHighHand(worse)


def test_best_five_of_seven_and_ties():
    a = pk.StandardHighHand.from_game("2c3d", "AsKsQsJsTs")
    b = pk.StandardHighHand.from_game("4h5h", "AsKsQsJsTs")
    assert a == b                        # both play the board
    assert HOLDEM.explain(a).label == "Royal flush"
