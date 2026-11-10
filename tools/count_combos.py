"""Exact number of different games the dealer can pick (every game, every
option, every add-on, every deck) that POKRR will deal to 2+ players.
Run:  .venv\\Scripts\\python.exe tools\\count_combos.py     (a few minutes, all CPU cores)"""
import itertools
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def count_one(args):
    fid, opts = args
    from engine.table import TableSettings
    from tools.combo_audit import DECKS, SPECIALS, SWAPS, WILDS
    n = 0
    for sp, wild, auction, swap, dice, bounty, deck in itertools.product(
            SPECIALS, WILDS, (False, True), SWAPS, (False, True), (False, True), DECKS):
        s = TableSettings(300, 10, 10, fid, tuple(sorted(opts.items())), sp[0], sp[1], sp[2],
                          swap[0], True, swap[1], swap[2], dice, bounty, wild, auction, deck)
        try:
            s.variant().validate(2)
            n += 1
        except Exception:
            pass
    return fid, n


def main():
    from engine.variants import FAMILIES
    jobs = [(fid, opts) for fid, fam in FAMILIES.items() for opts in fam.combos()]
    t0 = time.time()
    per = {}
    with ProcessPoolExecutor() as ex:
        for fid, n in ex.map(count_one, jobs, chunksize=2):
            per[fid] = per.get(fid, 0) + n
    for fid, n in per.items():
        print(f"{FAMILIES[fid].name:<22} {n:>10,}")
    print(f"{'TOTAL':<22} {sum(per.values()):>10,}   ({time.time() - t0:.0f}s, {len(jobs)} option sets)")


if __name__ == "__main__":
    main()
