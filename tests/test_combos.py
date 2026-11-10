"""Combination rules agreed with the owner on 2026-11-10 (docs/DECISIONS.md,
"Combination rules"): which game + add-on mixes are refused, and why."""
import pytest

from engine.table import TableSettings, addon_blocks, preview_choice
from engine.variants import VariantError


def build(vid="classic", opts=(), **kw):
    v = TableSettings(500, 10, 10, vid, tuple(sorted(dict(opts).items())), claim=True, **kw).variant()
    v.validate(3)
    return v


def refused(vid="classic", opts=(), match="", **kw):
    with pytest.raises(VariantError, match=match):
        build(vid, opts, **kw)


def test_one_wild_source_at_most():
    refused(wild="deuces", special_kind="joker", match="one kind of wild")
    refused(wild="jokers", auction=True, match="one kind of wild")
    refused(special_kind="jumping", auction=True, match="one kind of wild")
    refused("floors", wild="oneeyed", match="free jokers")
    refused("floors", special_kind="joker", match="free jokers")
    build(wild="deuces", special_kind="poison")            # poison isn't wild: fine
    build("floors", special_kind="poison")


def test_dice_only_on_one_board_of_five():
    build(dice=True)
    build("courchevel", dice=True)
    for vid in ("floors", "pyramid", "tictactoe", "rows", "double", "personal", "chowaha",
                "ironcross"):
        refused(vid, dice=True, match="Dice is only")
    refused(dice=True, wild="river", match="Dice can't")
    refused(dice=True, wild="queen", match="Dice can't")


def test_wild_river_needs_one_shared_river():
    build(wild="river")
    build("tictactoe", wild="river")                       # the centre card
    refused("personal", wild="river", match="exactly one shared river")
    refused("double", wild="river", match="exactly one shared river")
    refused("redriver", wild="river", match="exactly one shared river")
    refused("rows", {"layout": "2or3"}, wild="river", match="exactly one shared river")


def test_follow_the_queen_single_line_only():
    build(wild="queen")
    for vid in ("pyramid", "tictactoe", "floors", "ironcross", "chowaha", "double"):
        with pytest.raises(VariantError):
            build(vid, wild="queen")


def test_small_decks_hide_deuces_and_bounty():
    refused(deck="short", wild="deuces", match="no 2s")
    refused(deck="royal", bounty=True, match="no 7s or 2s")
    build(deck="short", wild="oneeyed")


def test_at_most_two_card_twists():
    build(pineapple="preflop", dice=True)
    build("blackjack", pineapple="preflop")
    refused("blackjack", pineapple="preflop", dice=True, match="at most two")


def test_pineapple_deals_extra_cards_only_when_needed():
    assert build(pineapple="preflop").hole_card_count == 2      # 1 left is enough (0-2 rule)
    assert build("floors", pineapple="preflop").hole_card_count == 7
    v = build("tictactoe", {"private": "2"}, pineapple="every", pine_count=2)
    assert v.hole_card_count == 8 and "extra private" in v.summary[-2]


def test_picker_lists_blocked_choices_with_reasons():
    st = TableSettings(500, 10, 10, "floors", (), claim=True)
    b = addon_blocks(st, 3)
    assert "deuces" in b["wild"] and "dice" in b and "auction" in b
    assert "poison" not in b.get("special_kind", {})
    pv = preview_choice(st, 3)
    assert pv["ok"] and pv["blocks"] == b
