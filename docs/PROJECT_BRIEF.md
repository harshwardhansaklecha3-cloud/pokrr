# Project brief — Private Poker Table

A private, browser-based poker table played with **play chips only** (no money,
payments, or gambling integrations). Play solo against local bots now; later,
invite friends to a private room by link or code, with humans and bots mixed.

## Core idea
A library of predefined **variations**. Before each hand the dealer picks one;
its rules decide the deck, dealing, board layout, reveal sequence, legal card
combinations, betting, and payouts. Variations are added one at a time, with
rules agreed in writing (see `DECISIONS.md`) and covered by tests.

## Non-negotiables
- Server is authoritative: it shuffles, deals, validates, and pays out.
  Browsers only send action requests.
- Each player (human or bot) only receives what they're entitled to see.
  No opponent hole cards or deck contents in payloads, logs, or debug output.
- Secure shuffle in real play (`secrets.SystemRandom`); deterministic, injectable
  randomness in tests.
- Chips are always conserved across the table.
- Bots obey exactly the same legal-action rules as humans, and see only
  their own cards plus public information.

## Variations
| Variation | Status |
|---|---|
| No-limit Texas Hold'em | Milestone 1 (baseline) |
| Pyramid | Milestone 2 — rule questions open, see `DECISIONS.md` |
| Elevator | Milestone 4 — rules not yet specified; do NOT implement until agreed |

## Stack (summary — details in `DECISIONS.md`)
Python 3.13/3.14 · PokerKit 0.7.7 (betting, pots, hand evaluation) ·
FastAPI + WebSockets · plain HTML/CSS/JavaScript (no build step) · pytest.
