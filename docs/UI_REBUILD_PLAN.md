# POKRR — UI rebuild plan ("back to basics") and going public

Written 2026-11-10 after the user's screenshots showed the 6-player Wall
Street view overlapping and the Raise button cut off with no way to scroll.

## Why rebuild
The current screen is one fixed-size canvas scaled to the window, with no
scrolling. Anything that doesn't fit gets cut off or overlaps, and every
device-specific fix (portrait / phoneland / desk) has piled patch rules onto
style.css (~600 lines of overrides). That is the source of the "bugging and
debugging".

## Principles
1. **A normal web page.** No scaled canvas. The page scrolls when content is
   taller than the screen. Nothing is ever cut off.
2. **Mobile-first, device-agnostic.** One layout that adapts with CSS:
   one column on phones, two columns (table | your hand + moves) from about
   900px wide, with a centred maximum width on big screens.
3. **Readable by default.** Body text ≥ 16px, sizes in `rem` with `clamp()`,
   tap targets ≥ 44px, card size from one variable (`--card`) that grows
   with the screen.
4. **Your moves always reachable.** On phones, a sticky bottom bar holds
   your cards and Fold / Check / Call / Raise. Building a raise opens a
   bottom sheet.
5. **Show less at once.** Opponent seats are compact (avatar, name, stack,
   card backs, last move); extra cards fan out with a count; tap a seat for
   details. Hints, history and rules sit behind taps.
6. **Dialogs are sheets.** Dealer's choice, results, claiming your hand,
   settings and rules open as scrollable sheets: full screen on phones,
   centred panels on laptops.
7. **One design system.** Tokens for colour, spacing, type and cards. The
   old portrait/phoneland/desk patch rules are deleted, not added to.
8. **Fast.** No build step, one CSS + one JS file, system fonts, cached
   static files, gzip.

## Test matrix (automated, run before every hand-over)
A script opens the game at each size and checks: no sideways overflow, the
action buttons are visible or reachable by scrolling, no overlapping seats,
and readable text sizes. It saves a screenshot of each.

| Device | Size |
|---|---|
| small Android | 360 × 740 |
| iPhone | 390 × 844 |
| phone sideways | 844 × 390 |
| iPad upright | 820 × 1180 |
| iPad sideways | 1180 × 820 |
| laptop | 1366 × 768 |
| desktop | 1920 × 1080 |

Scenarios: 2 players and a full 6-seat table; Hold'em, Wall Street (many
cards), Pyramid, Chowaha (tall boards), a showdown claim, the dealer's
choice, results.

## Phases
1. **Foundation:** remove the canvas scaling, new page skeleton and design
   tokens, scrolling allowed, plus the test-matrix script.
2. **The table:** seats, board (all game shapes), pots, your hand, a sticky
   action bar, phases (hit/buy/bid/pass/discard).
3. **Sheets:** dealer's choice, results and lessons, showdown claim,
   settings, rules/history, lobby.
4. **Polish:** animations (with reduced-motion respected), sounds, app icon
   and splash, accessibility pass.

The game engine, server and rules are not touched by this rebuild.

## Going public (after the rebuild)
1. **Repository prep (Claude):** `.gitignore` (venv, caches), MIT
   `LICENSE` (PokerKit is MIT too), README with run instructions, a
   `render.yaml` / start command for hosting. Check that no secrets or
   personal data are in the files.
2. **GitHub (the user):** create a GitHub account; install Git and the
   GitHub CLI (`winget install Git.Git`, `winget install GitHub.cli`); run
   `gh auth login` once (it opens the browser). After that Claude Code can
   run `git` / `gh` commands in this folder, each one approved by the user.
3. **Hosting:** Render's free web service. It connects to the GitHub repo
   and redeploys on every push. Free services sleep after 15 minutes without
   traffic (about 1 minute to wake), and rooms reset on a restart or deploy.
   WebSocket messages count as traffic. $7/month removes the sleep.
   Always-free alternatives: an Oracle Cloud Always Free VM (more setup), or
   the laptop plus a Cloudflare tunnel.
4. **Domain:** (2026-11-10: the owner will buy a new domain.) Point it at
   Render with a CNAME, add it as a custom domain in Render (free HTTPS), and set `SITE_URL`.
5. **Before announcing:** play-chips-only notice in the app and README; the
   limits that already exist (room cap, 6 seats); an App Store note (apps
   that simulate gambling are rated 17+).


## Status
- **Phase 1 done (2026-11-10).** The canvas scaling is gone and the page scrolls. The new stylesheet (`web/style.css`, written from scratch) gives:
  - **Phones upright:** a compact bar docked at the bottom with your cards and Fold / Call / Raise…; the chip tray opens on Raise….
  - **Phones sideways and wider:** two columns, with your hand and moves sticky on the right.
  - **Dialogs:** scroll, start at the top, and sit below nothing.
  - `tools/ui_check.py` checks 7 sizes × 6 situations, including "your cards and buttons are on the first screen". **All 42 pass.**
- **Next, Phase 2 (the table):** opponent seats more compact (less empty space, full names); a calmer docked "your hand"; action bubbles that don't cover the header on small screens; board sizing for tall boards (Pyramid, Chowaha); add tall-board and claim scenarios to the checker.- **Phase 2 done (2026-11-10).** The table:
  - **Phones (all compact layouts):** opponent seats are small cards in one row (avatar, name, chips, tiny cards, last move), so the board is always visible. Folded seats are dimmed. Ordinary action bubbles are skipped (each seat's tag shows its last move); claims, wins and BUST pop up centred on the seat. Banners are smaller.
  - **Your hand on phones:** one tidy row (avatar + chips | cards), "You have …" plus 💡 hints (folded by default), then the buttons. Hands with face-up cards (Wall Street) get their own row at a smaller size. The docked bar hugs its content, and the board fills the space above it.
  - **Bigger screens:** no reserved empty space in seats; the bot level sits under the name, so names aren't cut off. Upright tablets get larger compact seats.
  - The checker now also covers Pyramid, Chowaha, Tic-tac-toe and the Blackjack hit/stand turn (10 situations × 7 sizes). All layout checks pass. A "scenario did not complete" note means the checker's scripted play didn't reach that moment (for example, the bots went broke); it is not a layout fault.
- **Next, Phase 3 (the sheets):** dealer's choice, results/lessons, the showdown claim panel, settings, rules/history and the lobby. Make them readable and tidy on phones, with consistent headers and close buttons.
- **Phase 3 done (2026-11-10).** The panels:
  - Sheet headers (Rules, Settings) stay at the top with a ✕.
  - The dealer's choice keeps "Shuffle & deal" pinned at the bottom while the games scroll.
  - Claiming your hand: on phones the claim panel takes over from the bottom bar, and its "Lock in" row stays pinned. On compact screens the board scrolls into view when the claim starts.
  - The ☰ menu items all look the same; the lobby's code box fits.
  - The checker now covers 13 situations × 7 sizes = 91 screens, including Rules, Settings and the ☰ menu. **All pass.**
- **Next, Phase 4 (polish):** calmer animations (bubbles and banners, reduced motion), sound check, app icon and splash screen, an accessibility pass (labels, focus, contrast), and a final full check. Then publishing (GitHub, Render, a domain to be bought).
