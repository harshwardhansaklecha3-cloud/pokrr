"""Every game x option x add-on: does it build, does it play, and does it
look absurd? Run:  .venv\\Scripts\\python.exe tools\\combo_audit.py [--quick]

Prints, per kind of oddity, how many combinations hit it and examples.
The oddities are QUESTIONS for the owner, not automatic decisions."""
import itertools
import random
import sys
import time
import traceback
from collections import defaultdict

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from engine.table import Table, TableSettings          # noqa: E402
from engine.variants import FAMILIES                   # noqa: E402
from tests.test_soak import ChaosBot, run              # noqa: E402

QUICK = "--quick" in sys.argv
STRUCT = {"layout", "pot", "cards", "style", "market"}   # options that change the table shape

SPECIALS = [("none", "River", "private")] + [
    (k, st, sc) for k in ("joker", "poison", "jumping") for st in ("Flop", "Turn", "River")
    for sc in ("private", "all")]
WILDS = ["off", "deuces", "oneeyed", "jokers", "queen", "river"]
SWAPS = [("off", "off", 1), ("flop", "off", 1), ("every", "off", 1)] + [
    ("off", m, n) for m in ("preflop", "flop", "every") for n in (1, 2)]


DECKS = ["standard", "short", "royal"]


def settings(fid, opts, sp, wild, auction, swap, dice, bounty, deck="standard"):
    return TableSettings(300, 10, 10, fid, tuple(sorted(opts.items())), sp[0], sp[1], sp[2],
                         swap[0], True, swap[1], swap[2], dice, bounty, wild, auction, deck)


def label(fid, opts, sp, wild, auction, swap, dice, bounty):
    bits = [FAMILIES[fid].name]
    s = {k: v for k, v in opts.items() if k in STRUCT}
    if s:
        bits[0] += " (" + ", ".join(f"{k}={v}" for k, v in s.items()) + ")"
    if sp[0] != "none":
        bits.append(f"{sp[0]} card@{sp[1]}/{sp[2]}")
    if wild != "off":
        bits.append(f"wild={wild}")
    if auction:
        bits.append("auction")
    if swap[0] != "off":
        bits.append(f"anaconda={swap[0]}")
    if swap[1] != "off":
        bits.append(f"pineapple={swap[1]}x{swap[2]}")
    if dice:
        bits.append("dice")
    if bounty:
        bits.append("7-2 bounty")
    return " + ".join(bits)


def community(v):
    return [g for g in v.board_groups if g.id not in ("special", "dice")]


def oddities(v, fid, sp, wild, auction, swap, dice, bounty):
    """Which questions this combination raises: list of (kind, detail)."""
    out = []
    ranks = {repr(c)[0] for c in v.deck if not repr(c).startswith("X")}
    comm = community(v)
    from engine.table import _board_line
    rows_on_board = not _board_line(v)[0]
    wild_sources = [w for w in (
        "special joker card" if sp[0] in ("joker", "jumping") else "",
        f"wild rule {wild}" if wild != "off" else "",
        "joker auction" if auction else "",
        "built-in floor jokers" if fid == "floors" else "") if w]
    if wild == "deuces" and "2" not in ranks:
        out.append(("Deuces wild, but this deck has no 2s", ""))
    if bounty and not ({"7", "2"} <= ranks):
        out.append(("7-2 bounty, but this deck has no 7s or no 2s", ""))
    if wild == "river":
        reveal = [s for s in v.stages if any(g not in ("special", "dice") for g in s.reveal)]
        last = reveal[-1] if reveal else None
        n = sum(v.group(g).size for g in last.reveal if g not in ("special", "dice")) if last else 0
        if not last or not last.name.startswith("River"):
            out.append(("Wild river, but there is no shared river (the river is private)", ""))
        elif n != 1 or v.red_river:
            out.append(("Wild river, but there is more than one river card", ""))
    if wild == "queen" and rows_on_board:
        out.append(("Follow the Queen on a multi-part board (which card is 'next'?)", ""))
    if dice and (rows_on_board or sum(g.size for g in comm) != 5):
        out.append(("Dice on a board that isn't one line of 5 cards", ""))
    if dice and wild in ("river", "queen"):
        out.append(("Dice can replace the card that decided the wild rank", ""))
    if len(wild_sources) > 1:
        out.append(("More than one source of wild cards", " + ".join(wild_sources)))
    twists = [t for t in (
        "anaconda" if swap[0] != "off" else "", "pineapple" if swap[1] != "off" else "",
        "dice" if dice else "", "red river (built in)" if fid == "redriver" else "",
        "blackjack hits (built in)" if fid == "blackjack" else "",
        "market (built in)" if fid == "wallstreet" else "") if t]
    if len(twists) > 1:
        out.append(("Two card-changing twists at once", " + ".join(twists)))
    if wild_sources and fid == "blackjack":
        out.append(("Wild cards in Blackjack Hold'em (what does a wild count in the 21?)", ""))
    if wild_sources and fid == "hilo":
        out.append(("Wild cards in Hi-Lo (can a wild help the low hand?)", ""))
    if wild_sources and fid == "poker_patti":
        out.append(("Wild cards in Poker + Teen Patti", ""))
    if sp[0] != "none" and not any(g != "special" for s in v.stages if s.name == sp[1]
                                   for g in s.reveal):
        out.append((f"Special card turned up on a street with no shared card", ""))
    return out


def main():
    t0 = time.time()
    built = failed = 0
    odd = defaultdict(list)
    refused = defaultdict(int)
    playable = []
    for fid, fam in FAMILIES.items():
        seen = set()
        for opts in fam.combos():
            key = tuple(sorted((k, v) for k, v in opts.items() if k in STRUCT))
            if key in seen:
                continue
            seen.add(key)
            for sp, wild, auction, swap, dice, bounty, deck in itertools.product(
                    SPECIALS, WILDS, (False, True), SWAPS, (False, True), (False, True), DECKS):
                s = settings(fid, opts, sp, wild, auction, swap, dice, bounty, deck)
                try:
                    v = s.variant()
                    v.validate(3)
                except Exception as e:
                    failed += 1
                    refused[f"{fam.name}: {e}"] += 1
                    continue
                built += 1
                lab = label(fid, opts, sp, wild, auction, swap, dice, bounty) + (
                    f" + {deck} deck" if deck != "standard" else "")
                n_add = sum(x != y for x, y in zip(
                    (sp[0], wild, auction, swap[0], swap[1], dice, bounty, deck),
                    ("none", "off", False, "off", "off", False, False, "standard")))
                playable.append((s, lab, n_add))
                for kind, detail in oddities(v, fid, sp, wild, auction, swap, dice, bounty):
                    odd[kind].append((lab, detail))
    print(f"Game shapes x add-ons that can be dealt: {built:,}   refused: {failed:,}"
          f"   ({time.time() - t0:.0f}s)\n")
    print("Already refused (top reasons):")
    for r, n in sorted(refused.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {n:6,}  {r}")
    print("\nODDITIES (questions for the owner):")
    for kind, labs in sorted(odd.items(), key=lambda kv: -len(kv[1])):
        print(f"\n- {kind}: {len(labs):,} combinations")
        fams = sorted({lab.split(' + ')[0].split(' (')[0] for lab, _ in labs})
        print("  games:", ", ".join(fams))
        details = sorted({d for _, d in labs if d})
        if details:
            print("  mixes:", "; ".join(details[:12]))
        for lab, _ in random.Random(1).sample(labs, min(2, len(labs))):
            print("   e.g.", lab)

    # Play: every game shape with 0 or 1 add-on, plus a random sample of bigger mixes
    rng = random.Random(7)
    singles = [p for p in playable if p[2] <= 1]
    mixes = [p for p in playable if p[2] > 1]
    sample = singles + rng.sample(mixes, min(150 if QUICK else 1500, len(mixes)))
    print(f"\nPlaying {len(sample):,} combinations (3 hands each, 2 people + 1 bot)...")
    crashes = []
    t1 = time.time()
    for s, lab, _ in sample:
        try:
            tb = Table(seat_count=3, rng=rng, settings=s)
            bots = {}
            for i in range(3):
                tb.sit(i, f"P{i}", is_bot=(i == 2))
                bots[i] = ChaosBot(rng)
            run(tb, bots, 3, rng, humans={0, 1})
        except Exception as e:
            crashes.append((lab, f"{type(e).__name__}: {e}", traceback.format_exc(limit=4)))
    print(f"Played in {time.time() - t1:.0f}s. Crashes / rule breaks: {len(crashes)}")
    for lab, msg, _ in crashes[:25]:
        print(f"  x {lab}\n      {msg}")
    if crashes:
        print("\nfirst traceback:\n", crashes[0][2])


if __name__ == "__main__":
    main()
