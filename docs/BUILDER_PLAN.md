# Plan — "Build your own variation"

Goal: the dealer can invent a new game in the browser, without code, using
the same building blocks the built-in games use — then save it to the
library, play it with bots, and later share it with friends.

## What a game is made of (already in the engine)
| Block | Choices |
|---|---|
| Private cards | how many, dealt face down; optional extra cards per player on later streets, face up (Personal board) |
| Board groups | named card groups (a flop row, a shared turn, a pyramid row…) with a position on the table |
| Reveal order | which groups (and personal cards) are turned up before each betting round; burn or not |
| Rows | each row = one hand made from some groups; a group in several rows = a SHARED card |
| Row hand rule | Fix N private cards, or any (0…N); optional "max 1 card per group" (Pyramid) |
| Row hand type | poker (best 5) or Teen Patti (3 cards) |
| Private cards across rows | shared (usable in every row) or split before showdown (N to each row) |
| Pot | best row wins all, or split equally per row |
| Who picks cards | automatic best, or players pick (a weaker pick counts) |
| Add-ons | special card (Joker / Poison / Jumping joker; flop/turn/river; private or all cards), Anaconda passing |

## The builder screen (step by step, like dealing)
1. **Deal** — "How many private cards?" (+ optional face-up personal cards on turn/river).
2. **Lay out the table** — drag card groups onto a grid: add a row, set its
   size (1–5), mark a card as shared by several rows (it spans them). Live
   preview of the table shape.
3. **When is each card turned up?** — assign each group to Flop / Turn /
   River (and burn yes/no).
4. **How is each row played?** — per row: Fix 2 / Fix 3 / any; poker or Teen
   Patti; max one per group.
5. **Showdown & pot** — shared vs split private cards; best row wins vs split
   pot; auto best hand vs players pick.
6. **Add-ons** — default special card / Anaconda (still changeable per hand).
7. **Name it & test** — the server validates (enough cards for N players,
   every row can make a legal hand, minimum private cards), plays 200 quick
   bot hands to prove it runs and chips balance, then saves it.

## Safety rails (why it can't produce broken games)
- Every saved game goes through the same validation as built-in games.
- A row that can never make a legal hand, too few cards in the deck, or a
  split that doesn't divide evenly is rejected with a plain explanation.
- The automatic 200-hand bot run must pass before the game appears in the
  dealer's list.

## Storage
- Saved games are small JSON files (`variants/custom/*.json`) on the
  server — no accounts needed. Later, with online rooms, the host's custom
  games travel with the room.

## Build order
1. JSON format for a recipe + loader + validation (engine side) + tests.
2. Builder screen steps 1, 3, 4, 5 with a simple row editor (no drag yet).
3. Save / load / delete; custom games show in the dealer's list.
4. Visual grid editor (drag groups, shared cards spanning rows).
5. Share a custom game with friends (after online rooms exist).

## Still to agree with the user
- Should custom games allow more than 3 betting rounds after the deal (e.g.
  a "second turn")? The engine can do it; it changes the screen layout.
- Jokers in the deck itself (real joker cards) vs. the turned-up joker card.
