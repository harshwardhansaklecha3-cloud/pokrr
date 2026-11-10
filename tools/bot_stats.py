"""Measure how bots play: VPIP (how often they voluntarily put chips in
before the flop), PFR (how often they raise preflop), and how often hands
reach a showdown. Run: .venv\\Scripts\\python.exe tools\\bot_stats.py [hands]"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bots import BasicBot                      # noqa: E402
from engine.table import Table, TableSettings  # noqa: E402

HANDS = int(sys.argv[1]) if len(sys.argv) > 1 else 80
VARIANT = sys.argv[2] if len(sys.argv) > 2 else "classic"


def run(level: str):
    rng = random.Random(7)
    t = Table(seat_count=6, settings=TableSettings(1000, 10, 10, VARIANT), rng=rng)
    bots = {}
    for i in range(6):
        t.sit(i, f"B{i}", is_bot=True)
        bots[i] = BasicBot(random.Random(i), level=level)
        bots[i].fast = True                         # quick simulations for the test
    vpip, pfr, dealt, showdowns = Counter(), Counter(), Counter(), 0
    for _ in range(HANDS):
        for s in t.seats:                 # keep the table full: busted bots rebuy
            if s.stack == 0:
                t.rebuy(s.index)
        t.start_hand()
        for s in t.hand.seat_ids:
            dealt[s] += 1
        while t.hand_in_progress:
            seat = t.hand.actor_seat
            kind, amt = bots[seat].decide(t.view(seat), t.hand.variant)
            t.act(seat, kind, amt, seq=t.seq)
        pre = [h for h in t.hand.history if h["kind"] == "action" and h["street"] == "Preflop"]
        for seat in {h["seat"] for h in pre if h["action"] in ("call", "raise", "bet")}:
            vpip[seat] += 1
        for seat in {h["seat"] for h in pre if h["action"] in ("raise", "bet")}:
            pfr[seat] += 1
        showdowns += t.hand.result["showdown"]
    n = sum(dealt.values())
    return 100 * sum(vpip.values()) / n, 100 * sum(pfr.values()) / n, 100 * showdowns / HANDS


if __name__ == "__main__":
    print(f"{HANDS} hands, 6 bots each, variation {VARIANT}")
    print("level     VPIP%  PFR%  showdown%   (typical humans at a 6-seat table: VPIP 25-45%)")
    for level in ("noob", "amateur", "tycoon"):
        v, p, sd = run(level)
        print(f"{level:8}  {v:5.1f}  {p:4.1f}  {sd:6.1f}")
