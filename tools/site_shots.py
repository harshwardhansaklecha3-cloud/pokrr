"""Takes the website's game screenshots: deals each game against bots in a
real (headless) browser and photographs the table once the board is out.
Saves JPEGs to web/shots/ (used by the home page and the game pages).

Run:  .venv\\Scripts\\python.exe tools\\site_shots.py          (all, ~3 min)
      .venv\\Scripts\\python.exe tools\\site_shots.py pyramid  (one)
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_check import JS_HELPERS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "shots"
sys.stdout.reconfigure(encoding="utf-8")

BASE = {"special_kind": "none", "special_stage": "River", "special_scope": "private",
        "anaconda": "off", "pineapple": "off", "pine_count": 1, "dice": False, "bounty": False,
        "wild": "off", "auction": False, "deck": "standard", "small_blind": 10, "big_blind": 10}
# file name -> (game id, options, add-ons)
SHOTS = {
    "classic": ("classic", {"private": "2", "rule": "any"}, {}),
    "double": ("double", {}, {}),
    "rows": ("rows", {"layout": "elevator"}, {}),
    "pyramid": ("pyramid", {}, {}),
    "personal": ("personal", {}, {}),
    "poker-patti": ("poker_patti", {}, {}),
    "floors": ("floors", {}, {}),
    "tictactoe": ("tictactoe", {}, {}),
    "redriver": ("redriver", {}, {}),
    "hilo": ("hilo", {}, {}),
    "courchevel": ("courchevel", {}, {}),
    "ironcross": ("ironcross", {}, {}),
    "chowaha": ("chowaha", {}, {}),
    "blackjack": ("blackjack", {}, {}),
    "wallstreet": ("wallstreet", {}, {}),
    "pineapple": ("classic", {"private": "2", "rule": "any"}, {"pineapple": "preflop"}),
    "anaconda": ("classic", {"private": "4", "rule": "fix2"}, {"anaconda": "flop"}),
    "wild": ("classic", {"private": "2", "rule": "any"}, {"wild": "jokers"}),
}

# Play along (check/call, stand, cheapest buy, drop, pass) until the board is out.
STEP = r"""() => {
  if (!state || !state.hand_active) return 'over';
  const v = state.variant;
  const groups = v.board_groups.filter(g => !g.hidden && !g.optional);
  const full = groups.length > 0 && groups.every(g => (state.board[g.id] || []).length === g.size);
  const wall = v.market && v.market.length && !state.buy && state.legal;
  if ((full || wall) && (state.legal || state.declare)) return 'ready';
  if (state.legal) send({type: 'action', action: state.legal.check ? 'check' : 'call', seq: state.seq});
  else if (state.pass) send({type: 'pass', card: state.pass.cards[0], seq: state.seq});
  else if (state.hit) send({type: 'stand', seq: state.seq});
  else if (state.buy) send(state.buy.can_afford.length ? {type: 'buy', card: state.buy.can_afford[0], seq: state.seq} : {type: 'market_fold', seq: state.seq});
  else if (state.auction && state.auction.max != null) send({type: 'drop', seq: state.seq});
  else if (state.declare) send({type: 'declare', declaration: __t.claim(), seq: state.seq});
  return 'step';
}"""


def main(only: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**__import__("os").environ, "POKER_BOT_DELAY": "0.05"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(port),
                               "--log-level", "warning"], cwd=ROOT, env=env)
    done = 0
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for size, (w, h, scale) in {"desk": (1280, 800, 1), "phone": (390, 844, 2)}.items():
                page = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
                page.goto(f"http://127.0.0.1:{port}/play")
                page.wait_for_function("document.getElementById('conn').textContent.includes('connected')")
                page.evaluate(JS_HELPERS)
                page.evaluate("""() => { document.getElementById('your-name').value = 'You';
                    document.querySelector('#setup [name=bots]').value = '3';
                    document.querySelector('#setup button[type=submit]').click(); }""")
                page.wait_for_function("() => state && state.catalogue")
                names = [n for n in SHOTS if not only or n in only]
                if size == "phone":
                    names = [n for n in names if n in ("classic", "pyramid", "floors", "tictactoe")]
                for name in names:
                    vid, opts, add = SHOTS[name]
                    for attempt in range(4):
                        for _ in range(900):               # finish any hand still going
                            if page.evaluate(STEP) == "over":
                                break
                            time.sleep(0.15)
                        else:
                            print(f"  {name}: previous hand never ended:",
                                  page.evaluate("() => JSON.stringify({stage: state.stage, actor: state.actor, "
                                                "legal: !!state.legal, declare: !!state.declare, pass: !!state.pass, "
                                                "awaiting: state.awaiting, err: document.getElementById('error').textContent})"),
                                  flush=True)
                        page.evaluate("() => { if (state.seats[state.you].stack === 0) send({type: 'rebuy'}); }")
                        time.sleep(0.4)
                        start = page.evaluate("() => state.hand_no")
                        sel = {**BASE, "variant_id": vid, "options": opts, **add}
                        page.evaluate(f"() => send(Object.assign({{type: 'start_hand'}}, {json.dumps(sel)}))")
                        page.wait_for_function(f"() => state.hand_no > {start}", timeout=15000)
                        res = "step"
                        print(f"  dealing {name} ({size})", flush=True)
                        for _ in range(300):
                            res = page.evaluate(STEP)
                            if res in ("ready", "over"):
                                break
                            time.sleep(0.15)
                        if res == "ready":
                            time.sleep(1.2)                       # let the deal animation settle
                            page.evaluate("() => { document.querySelectorAll('#fx > *').forEach(x => x.remove()); window.scrollTo(0, 0); }")
                            path = OUT / (f"{name}.jpg" if size == "desk" else f"{name}-phone.jpg")
                            page.screenshot(path=str(path), type="jpeg", quality=78)
                            print(f"saved {path.name} ({path.stat().st_size // 1024} KB)", flush=True)
                            done += 1
                            # finish the hand quickly: fold
                            page.evaluate("() => { if (state.legal && state.legal.fold) send({type: 'action', action: 'fold', seq: state.seq}); }")
                            for _ in range(300):
                                if page.evaluate(STEP) == "over":
                                    break
                                time.sleep(0.1)
                            break
                        print(f"  {name}: hand ended early, dealing again")
                page.close()
            br.close()
    finally:
        server.terminate()
    print(f"{done} screenshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
