# Implementation plan — POKRR

Status legend: [x] done · [~] partly · [ ] not started

## Milestone 1 — local No-Limit Hold'em vs bots — done
- [x] PokerKit research + probes (`research/`), engine, bots, tests, server, UI

## Milestone 2 — variation library (in progress)
- [x] Variation recipe engine (rows, shared/split cards, fix N / 012, scoring)
- [x] Presets: Hold'em (012/Fix 2), Omaha, Double Board Hold'em/Omaha
      (split/shared), Pyramid, Elevator, Twin Rows, 2or3
- [x] Dealer's choice before every hand (human picks vs bots), rules summary
- [x] Showdown choices: split cards between rows / pick your own cards;
      bots pick best; cards stay hidden until everyone has chosen
- [x] UI: POKRR name, Leave table, chip-denomination betting, deal/shuffle/
      chip animations, action bubbles, FOLDED stamp, dealer/all-in badges,
      separate side pots, chips-on-table total
- [ ] "Custom game" builder form (private cards, rows, cards per row, shared
      cards, hand rule, scoring) — engine supports it; needs the screen
- [ ] Jokers / wild cards / poison card — rules to agree first
- [ ] Bots: smarter play in multi-row games (currently legal but basic)

## Milestone 3 — online private rooms
- [ ] Rooms with codes/links, seats, nicknames, room-scoped session tokens
- [ ] Mixed human/bot seats, reconnect without duplicating seats
- [ ] Rotating dealer's choice between humans; declaration timers
- [ ] Deployment plan + cost estimate; test locally before any account setup
