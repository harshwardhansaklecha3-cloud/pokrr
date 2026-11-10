"""Checks the "one thing at a time" pacing in a real browser (headless):
an all-in run-out deals flop, turn and river one by one; the dice roll is
shown before the card changes; Pineapple throw-aways fly off before the
next cards. Saves screenshots to tools/ui_shots/pace-*.png.

Run:  .venv\\Scripts\\python.exe tools\\pace_check.py
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_check import JS_HELPERS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "tools" / "ui_shots"
sys.stdout.reconfigure(encoding="utf-8")

OBSERVER = r"""
window.__plog = [];
window.__t0 = performance.now();
new MutationObserver(() => {
  const n = [...document.querySelectorAll('#board [data-key^="b-"]')].map(e => e.dataset.code).join(' ');
  const dice = document.querySelector('.dice-fx .dice-text');
  const fly = document.querySelectorAll('.fxcard').length;
  const rec = { t: Math.round(performance.now() - __t0), hand: state && state.hand_no, n,
                dice: dice ? dice.textContent : '', fly };
  const last = __plog[__plog.length - 1];
  if (!last || last.n !== rec.n || last.dice !== rec.dice || last.fly !== rec.fly) __plog.push(rec);
}).observe(document.body, { childList: true, subtree: true, characterData: true });
"""


def deal_js(extra: dict) -> str:
    sel = {"variant_id": "classic", "options": {"private": "2", "rule": "any"},
           "special_kind": "none", "special_stage": "River", "special_scope": "private",
           "anaconda": "off", "pineapple": "off", "pine_count": 1, "dice": False,
           "bounty": False, "wild": "off", "auction": False, "deck": "standard",
           "small_blind": 10, "big_blind": 10, **extra}
    return f"send(Object.assign({{type: 'start_hand'}}, {json.dumps(sel)}))"


STEP = r"""(allin) => {
  if (pacing) return 'pacing';
  if (state.legal) {
    const L = state.legal;
    if (allin && L.raise_kind) send({type: 'action', action: L.raise_kind, amount: L.max_to, seq: state.seq});
    else send({type: 'action', action: L.call ? 'call' : 'check', seq: state.seq});
    return 'acted';
  }
  if (state.pass) { send({type: 'pass', card: state.pass.cards[0], seq: state.seq}); return 'passed'; }
  if (state.declare) { send({type: 'declare', declaration: __t.claim(), seq: state.seq}); return 'claimed'; }
  return 'wait';
}"""


def play(page, extra, allin, want, shots, tries=12, other=None):
    """Deal hands until ``want(log_of_hand)`` holds; screenshot along the way."""
    for k in range(tries):
        page.wait_for_function("() => state && !state.hand_active && !pacing && paceQueue.length === 0",
                               timeout=120000)
        for pg in (page, other) if other is not None else (page,):
            pg.evaluate("() => { if (state.seats[state.you].stack === 0) send({type: 'rebuy'}); }")
        time.sleep(0.6)
        page.evaluate("() => { modalHidden = false; }")
        start = page.evaluate("() => state.hand_no")
        page.evaluate(deal_js(extra))
        page.wait_for_function(f"() => state.hand_no > {start}", timeout=10000)
        hand = start + 1
        taken = set()
        end = time.time() + 120
        while time.time() < end:
            page.evaluate(STEP, allin)
            if other is not None:
                other.evaluate(STEP, False)          # the friend just calls
            for name, test in shots.items():
                if name not in taken and page.evaluate(test):
                    page.screenshot(path=str(SHOTS / f"pace-{name}.png"))
                    taken.add(name)
            if page.evaluate("() => !state.hand_active && !pacing && paceQueue.length === 0"):
                break
            time.sleep(0.12)
        log = [x for x in page.evaluate("() => __plog") if x["hand"] == hand]
        if want(log):
            return log, taken
    return None, set()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(port),
                               "--log-level", "warning"], cwd=ROOT)
    ok = True
    try:
        import urllib.request
        for _ in range(120):                       # wait until the server answers
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/play")
            page.evaluate(JS_HELPERS)
            page.evaluate("() => { window.PACE_OFF = false; }")
            page.evaluate("""() => {
                document.getElementById('your-name').value = 'Tester';
                document.querySelector('#setup [name=bots]').value = '0';
                document.querySelector('#setup button[type=submit]').click(); }""")
            page.wait_for_function("() => state && state.catalogue", timeout=10000)
            page.evaluate(OBSERVER)
            # a friend joins (a second browser) and calls every all-in
            code = page.evaluate("() => roomInfo.code")
            ctx2 = br.new_context(viewport={"width": 390, "height": 844})
            friend = ctx2.new_page()
            friend.goto(f"http://127.0.0.1:{port}/play?room={code}")
            friend.evaluate(JS_HELPERS)
            friend.evaluate("() => { window.PACE_OFF = false; }")
            friend.evaluate("""() => { document.getElementById('your-name').value = 'Friend';
                document.querySelector('#join button[type=submit], #join button').click(); }""")
            friend.wait_for_function("() => state && state.you != null", timeout=10000)

            # 1. all-in run-out + dice
            def runout(log):
                return any(x["dice"] for x in log) and any(len(x["n"].split()) == 4 for x in log)
            log, taken = play(page, {"dice": True}, True, runout, other=friend, shots={
                "runout-turn": "() => pacing && document.querySelectorAll('#board [data-key^=\"b-\"]').length === 4",
                "dice-rolled": "() => { const d = document.querySelector('.dice-fx .dice-text'); return d && d.textContent.startsWith('Rolled'); }",
            })
            if not log:
                print("✗ no all-in run-out with dice happened"); ok = False
            else:
                print("All-in run-out with dice (ms since start, board, dice text):")
                base = log[0]["t"]
                for x in log:
                    print(f"  {x['t'] - base:6d}  {x['n']:<20}  {x['dice']}")
                boards = [x for x in log if x["n"] and not x["dice"]]
                sizes = [len(x["n"].split()) for x in boards]
                steps = [x["t"] for x in boards if len(x["n"].split()) in (3, 4, 5)]
                gaps_ok = all(b - a >= 1200 for a, b in zip(steps, steps[1:3]))
                print(f"  streets one by one: {'yes' if gaps_ok and 4 in sizes else 'NO'};"
                      f" screenshots: {sorted(taken)}")
                ok &= gaps_ok and 4 in sizes and "dice-rolled" in taken

            # 2. Pineapple throw-away before the flop
            log, taken = play(page, {"pineapple": "preflop"}, False,
                              lambda lg: any(x["fly"] for x in lg),
                              {"throwaway": "() => document.querySelectorAll('.fxcard').length > 0"},
                              other=friend)
            if not log:
                print("✗ no throw-away animation seen"); ok = False
            else:
                fly = next(x for x in log if x["fly"])
                flop = next((x for x in log if len(x["n"].split()) >= 3 and x["t"] > fly["t"]), None)
                gap = flop["t"] - fly["t"] if flop else None
                print(f"Pineapple: card flies off, flop {gap} ms later; screenshots: {sorted(taken)}")
                ok &= gap is not None and gap >= 900
            br.close()
    finally:
        server.terminate()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
