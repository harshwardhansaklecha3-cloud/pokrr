"""POKRR screen check: opens the game at 7 screen sizes and several game
situations, checks the layout, and saves a screenshot of each.

Checks (per size x situation):
  - no sideways scrolling (page no wider than the screen)
  - every visible button can be reached (scrolled to) and isn't covered
  - opponent seats don't overlap each other
  - smallest visible text size (warns under 12px)

Run:   .venv\\Scripts\\python.exe tools\\ui_check.py            (all)
       .venv\\Scripts\\python.exe tools\\ui_check.py iphone      (one size)
Screenshots go to tools/ui_shots/. Needs Playwright (dev tool):
       .venv\\Scripts\\python.exe -m pip install playwright
       .venv\\Scripts\\python.exe -m playwright install chromium
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "tools" / "ui_shots"
SIZES = {
    "android":   (360, 740, True),
    "iphone":    (390, 844, True),
    "phoneland": (844, 390, True),
    "ipad":      (820, 1180, True),
    "ipadland":  (1180, 820, True),
    "laptop":    (1366, 768, False),
    "desktop":   (1920, 1080, False),
}

# --- driving the game from inside the page (uses the page's own globals) ---
JS_HELPERS = r"""
window.PACE_OFF = true;     // layout check: skip the one-at-a-time replays (tools/pace_check.py tests them)
window.__t = {
  sleep: (ms) => new Promise(r => setTimeout(r, ms)),
  async until(fn, ms = 15000) {
    const end = Date.now() + ms;
    while (Date.now() < end) { try { if (fn()) return true; } catch (e) {} await __t.sleep(100); }
    return false;
  },
  click(sel, text) {
    const b = [...document.querySelectorAll(sel)].find(x => !text || x.textContent.includes(text));
    if (b) b.click(); return !!b;
  },
  // A legal claim for the first claimable row (just to get past a showdown).
  claim() {
    const v = state.variant, r = v.rows.find(x => x.kind !== 'bj21');
    if (r.kind === 'teen_patti') return {[r.id]: {hole: state.declare.hole.slice(0, 3), board: []}};
    const k = Math.min(...r.hole_use), jk = Math.max(0, Math.min(r.jokers || 0, 5 - k));
    let b = r.one_per_group ? r.groups.map(g => (state.board[g] || [])[0]).filter(Boolean)
                            : r.groups.flatMap(g => state.board[g] || []);
    return {[r.id]: {hole: state.declare.hole.slice(0, k), board: b.slice(0, 5 - k - jk)}};
  },
  // Answer whatever the table is waiting for from us (cheaply).
  async step(fold) {
    if (state.legal) send({type: 'action', seq: state.seq,
      action: fold && state.legal.fold ? 'fold' : (state.legal.check ? 'check' : 'call')});
    else if (state.buy) send(state.buy.can_afford.length ? {type: 'buy', card: state.buy.can_afford[0], seq: state.seq}
                                                          : {type: 'market_fold', seq: state.seq});
    else if (state.hit) send({type: 'stand', seq: state.seq});
    else if (state.auction && state.auction.max != null) send({type: 'drop', seq: state.seq});
    else if (state.pass) send({type: 'pass', card: state.pass.cards[0], seq: state.seq});
    else if (state.declare) send({type: 'declare', declaration: __t.claim(), seq: state.seq});
    await __t.sleep(150);
  },
  // Finish the hand (folding when we can) and open the game picker.
  async toPicker() {
    for (let i = 0; i < 400 && state.hand_active; i++) await __t.step(true);
    await __t.until(() => !document.getElementById('modal').hidden, 20000);
    if (!document.querySelector('#picker .families')) __t.click('#picker button', 'Choose the next game');
    await __t.until(() => document.querySelector('#picker .families'));
    if (state.seats[state.you].stack === 0) { send({type: 'rebuy'}); await __t.sleep(400); }
  },
  // Deal a game and play along until cond() is true.
  async dealUntil(family, cond) {
    await __t.toPicker();
    __t.click('#picker .families .preset', family); await __t.sleep(300);
    __t.click('#picker button', 'Shuffle');
    for (let i = 0; i < 400; i++) {
      await __t.sleep(50);
      try { if (cond()) return true; } catch (e) {}
      if (!state.hand_active && state.hand_no) return false;
      await __t.step(false);
    }
    return false;
  },
};
"""

SCENARIO_JS = {
    # lobby: nothing to do
    "lobby": "async () => true",
    # first dealer's choice with a full table
    "picker": r"""async () => {
        document.getElementById('your-name').value = 'Tester';
        document.querySelector('#setup [name=bots]').value = '5';
        document.querySelector('#setup button[type=submit]').click();
        return await __t.until(() => document.querySelector('#picker .families'));
    }""",
    # 6 seats, Hold'em, your turn
    "table": r"""async () => {
        __t.click('#picker .families .preset', 'Classic board');
        await __t.sleep(300);
        __t.click('#picker button', 'Shuffle');
        return await __t.until(() => state && state.legal);
    }""",
    # showdown: claim your hand
    "claim": r"""async () => {
        for (let i = 0; i < 200; i++) {
          if (state.declare) return true;
          if (!state.hand_active) return false;
          if (state.legal) send({type: 'action', action: state.legal.check ? 'check' : 'call', seq: state.seq});
          await __t.sleep(150);
        }
        return !!state.declare;
    }""",
    # results after claiming the best hand
    "results": r"""async () => {
        const b = Object.values(state.board).flat();
        pick.rows[Object.keys(pick.rows)[0]].board = b.slice(0, 5);
        redrawPick(); await __t.sleep(200);
        __t.click('#declare button', 'Lock in');
        return await __t.until(() => !document.getElementById('modal').hidden, 20000);
    }""",
    # Wall Street, 6 seats: lots of face-up cards
    "wallstreet": r"""async () => {
        if (!document.querySelector('#picker .families')) __t.click('#picker button', 'Choose the next game');
        await __t.until(() => document.querySelector('#picker .families'));
        if (state.seats[state.you].stack === 0) { send({type: 'rebuy'}); await __t.sleep(400); }
        __t.click('#picker .families .preset', 'Wall Street'); await __t.sleep(300);
        __t.click('#picker button', 'Shuffle');
        for (let i = 0; i < 300; i++) {
          if (state.legal) return true;
          if (state.buy) {
            const ok = state.buy.can_afford;
            send(ok.length ? {type: 'buy', card: ok[0], seq: state.seq} : {type: 'market_fold', seq: state.seq});
            await __t.sleep(300);
          }
          await __t.sleep(150);
        }
        return !!state.legal;
    }""",
    # tall and unusual boards, and the Blackjack hit/stand turn
    "pyramid": "async () => __t.dealUntil('Pyramid', () => state.legal && state.stage !== 'Preflop')",
    "chowaha": "async () => __t.dealUntil('Chowaha', () => state.legal && state.stage === 'River')",
    "tictactoe": "async () => __t.dealUntil('Tic-tac-toe', () => state.legal && state.stage === 'River')",
    "blackjack": "async () => __t.dealUntil('Blackjack', () => !!state.hit)",
    # the sheets and the phone menu
    "rules": r"""async () => { document.getElementById('info-btn').click();
        return await __t.until(() => !document.getElementById('info-modal').hidden); }""",
    "settings": r"""async () => { document.getElementById('info-close').click();
        document.getElementById('settings-btn').click();
        return await __t.until(() => !document.getElementById('settings-modal').hidden); }""",
    "menu": r"""async () => { document.getElementById('settings-close').click(); await __t.sleep(200);
        const m = document.getElementById('menu-btn');
        if (getComputedStyle(m).display === 'none') return true;      // wide screens: no menu
        m.click(); return await __t.until(() => document.body.classList.contains('menu-open')); }""",
}
SCENARIOS = list(SCENARIO_JS)

CHECK_JS = r"""() => {
  const out = {problems: [], minFont: 99};
  const W = innerWidth;
  if (document.documentElement.scrollWidth > W + 1)
    out.problems.push(`page is ${document.documentElement.scrollWidth}px wide on a ${W}px screen`);
  const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden]'); };
  // buttons: reachable and not covered
  const sheet = ['settings-modal', 'info-modal', 'modal'].map(id => document.getElementById(id)).find(m => m && !m.hidden);
  const modalOpen = !!sheet;
  const menuOpen = document.body.classList.contains('menu-open');
  const scope = sheet ? `#${sheet.id} button` : menuOpen ? '#tools button' : '#screen button';
  for (const b of document.querySelectorAll(scope)) {
    if (!visible(b) || (!menuOpen && b.closest('.tools'))) continue;
    b.scrollIntoView({block: 'center', inline: 'center'});
    const r = b.getBoundingClientRect();
    const label = b.textContent.trim().slice(0, 20);
    if (r.right > W + 1 || r.left < -1) { out.problems.push(`button "${label}" is off the side`); continue; }
    if (r.bottom > innerHeight + 1 || r.top < -1) { out.problems.push(`button "${label}" can't be scrolled into view`); continue; }
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (top && top !== b && !b.contains(top) && !top.closest('.fx') && !top.closest('.bubble') && !top.closest('.error'))
      out.problems.push(`button "${b.textContent.trim().slice(0,20)}" is covered by ${top.className || top.tagName}`);
  }
  window.scrollTo(0, 0);
  document.querySelectorAll('.side, .modal').forEach(e => (e.scrollTop = 0));
  // when it's your turn: your cards and your first move must be on the FIRST screen
  if (!modalOpen && typeof state !== 'undefined' && state && state.legal) {
    const inView = (e) => { if (!e) return false; const r = e.getBoundingClientRect();
      return r.top >= -1 && r.bottom <= innerHeight + 1 && r.left >= -1 && r.right <= W + 1; };
    if (!inView(document.querySelector('#me .card'))) out.problems.push("your cards aren't visible without scrolling");
    if (!inView(document.querySelector('#controls button'))) out.problems.push("your move buttons aren't visible without scrolling");
    const me = document.querySelector('#me .card'), btn = document.querySelector('#controls button');
    for (const e of [me, btn]) if (e) { const r = e.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (top && !e.contains(top) && top !== e && !top.closest('.fx') && !top.closest('.bubble') && !top.closest('.ctag') && !top.closest('.error'))
        out.problems.push(`${e === me ? 'your cards are' : 'your buttons are'} covered by ${top.className || top.tagName}`); }
  }
  // opponent seats must not overlap
  const tiles = [...document.querySelectorAll('.opponents .player')].filter(visible).map(e => e.getBoundingClientRect());
  for (let i = 0; i < tiles.length; i++) for (let j = i + 1; j < tiles.length; j++) {
    const a = tiles[i], b = tiles[j];
    if (a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2)
      out.problems.push(`seats ${i} and ${j} overlap`);
  }
  // smallest text actually on screen
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue;
    const e = n.parentElement; if (!e || !visible(e) || e.closest('.fx') || e.closest('#safe-probe')) continue;
    const z = parseFloat(getComputedStyle(e).zoom || '1') || 1;
    const f = parseFloat(getComputedStyle(e).fontSize) * z;
    if (f < 1) continue;                                   // deliberately hidden text
    if (f < out.minFont) { out.minFont = f; out.minText = n.textContent.trim().slice(0, 24); }
  }
  return out;
}"""


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def main(only: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    port = free_port()
    env = dict(os.environ, POKER_BOT_DELAY="0.05")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(port),
                               "--log-level", "warning"], cwd=ROOT, env=env)
    failures = 0
    try:
        import urllib.request
        for _ in range(120):                       # wait until the server answers
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for name, (w, h, touch) in SIZES.items():
                if only and name not in only:
                    continue
                ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=touch,
                                          is_mobile=touch and w < 900, device_scale_factor=2 if touch else 1)
                page = ctx.new_page()
                page.goto(f"http://127.0.0.1:{port}/play")
                page.wait_for_function("document.getElementById('conn').textContent.includes('connected')")
                page.evaluate(JS_HELPERS)
                for sc in SCENARIOS:
                    ok = page.evaluate(SCENARIO_JS[sc])
                    page.wait_for_timeout(2600 if sc in ("results",) else 900)
                    rep = page.evaluate(CHECK_JS)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(SHOTS / f"{name}-{sc}.png"))                  # what you see first
                    page.screenshot(path=str(SHOTS / f"{name}-{sc}-full.png"), full_page=True)
                    status = "ok " if ok and not rep["problems"] else "BAD"
                    if status == "BAD":
                        failures += 1
                    font = f"smallest text {rep['minFont']:.0f}px" + (f" ('{rep.get('minText')}')" if rep['minFont'] < 12 else "")
                    print(f"{status} {name:9} {sc:10} {'' if ok else '(scenario did not complete) '}{font}")
                    for p in rep["problems"][:6]:
                        print(f"      - {p}")
                ctx.close()
            browser.close()
    finally:
        server.terminate()
    print(f"\n{'All checks passed' if not failures else f'{failures} problem screen(s)'}; screenshots in {SHOTS}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
