# Decision log

Newest decisions at the bottom of each section. "Agreed" = confirmed by the
user. "Default" = a routine choice made by the developer that can be revisited.

## PokerKit research (2026-11-08)
Sources:
- Repository: https://github.com/uoftcprg/pokerkit (MIT license)
- PyPI: https://pypi.org/project/pokerkit/ (0.7.7, released 2026-10-12, Python >= 3.11)
- Docs: https://pokerkit.readthedocs.io/en/stable/ — see
  `simulation.html` (State, Street, operations) and `evaluation.html` (hands)

Verified by running `research/pokerkit_probe.py` and `research/pokerkit_probe2.py`
against PokerKit 0.7.7 on Python 3.14.3 (PyPI classifiers only list 3.11–3.13,
but it ran fine; it has zero dependencies):
- Blinds, preflop/postflop action order, heads-up blind reversal: correct.
- Minimum raise enforced (raise-to 17 rejected after a raise to 10 with BB 2;
  raise-to 3 rejected with BB 2).
- Short all-in raise does NOT reopen betting for players who already acted.
- Side pots computed with correct eligibility; uncalled excess returned.
- Split pots: odd chip goes to the first seat left of the button (verified
  207-chip pot → 104 / 103).
- Early win when everyone folds.
- `push_chips()` returns `ChipsPushing(amounts, pot_index, ...)` per pot,
  which we use for "who won which pot" explanations.
- Hand evaluation: `StandardHighHand.from_game(hole, board)` → `.cards`,
  `.entry.label` (e.g. "Straight flush"). ~3,600 7-card evaluations/second.
- Custom hand rules: showdown calls `hand_type.from_game(hole, board)` with
  the board in deal order, so a variant can supply its own Hand subclass. A
  Pyramid "one card per row" prototype worked (AA with four kings on the
  board correctly lost to two pair because only one king is selectable).

Limitations found and how we handle them:
1. PokerKit shuffles its internal deck with Python's `random` (not secure).
   → We never let PokerKit choose cards. We pass every hole, board and burn
     card explicitly from our own `Shoe` (shuffled with `secrets.SystemRandom`).
     Automations for hole dealing, board dealing and burning are OFF.
2. Dealing a card that was already dealt is only a *warning* in PokerKit.
   → Our shoe guarantees uniqueness, and the engine turns PokerKit warnings
     into errors.
3. Multiple boards in PokerKit means "the same deal applied to several boards"
   (run-it-twice), not differently-shaped boards. → Board groups/rows are our
   own concept; we deal them into PokerKit's single board in a fixed order
   and the variant's hand type knows where each row starts.
4. Splitting a pot into several "portions" is natively done per hand type
   (used for hi/lo games). It might suit Elevator's three row portions, but
   Elevator's per-player pair assignment isn't something PokerKit models.
   → Decide when Elevator's rules are agreed; fallback is our own payout
     step using PokerKit's pot amounts and eligibility lists.

5. PokerKit's automatic "hand killing" removes losing hands from each pot's
   eligible list and clears their hole cards before chips are pushed.
   → Hand killing runs manually; we snapshot pots first, and evaluate shown
     hands from the cards recorded at show time (found in browser testing;
     regression test in `tests/test_table_and_views.py`).

Conclusion: no blocker. PokerKit owns betting, pots, and hand ranking; we own
the deck, dealing, board layout, seat/button management, views, and bots.

## Architecture (Default)
- Four separate layers: `engine/` (table + PokerKit wrapper), `engine/variants/`
  (dealing, layout, hand rules per variation), `bots/`, and `server/` + `web/`.
- Backend: Python + FastAPI + WebSockets (uvicorn). Even single-player runs
  through the server, so multiplayer later doesn't require a rewrite.
- Frontend: plain HTML/CSS/JS served by the same server. No build tools.
- Variation = a typed Python dataclass (deck, hole cards, board groups,
  stages, hand type, rules summary) plus optional small code (a Hand class).
  No universal rules language.
- Every state change bumps a sequence number; actions must quote the current
  number, so duplicate or stale clicks are rejected.

## Table rules (Default — tell us if you want different house rules)
- Moving button: the button moves to the next seat that still has chips.
  (Not the casino "dead button" rule; simpler and fine for home games.)
- Players with 0 chips are "busted" and skipped. A busted human can rebuy
  to the starting stack between hands. Busted bots stay out.
- At showdown, all players still in the hand reveal their cards (no mucking),
  so the explanation can show everyone's best hand. Folded hands stay hidden
  (shown as face-down cards stamped FOLDED).
- "Leave table" ends the game and returns to the start screen (play chips,
  nothing is saved).
- Odd chips in split pots: first seat left of the button (PokerKit default).
- Next-hand settings (blinds, stacks, variation) never affect a hand in progress.

## Double boards in PokerKit (verified 2026-11-08, `research/pokerkit_probe3_double_board.py`)
`starting_board_count=2` deals two separate boards (one `deal_board` call
per board, different cards), splits each pot half per board, and gives the
whole pot to a player who wins both. Works with Hold'em and Omaha hand rules.
It assumes a player's private cards can be used on BOTH boards. If cards
must instead be split between rows, we need a small custom step.
It cannot model community cards shared by several rows (Elevator's turn
and river). Elevator will use one PokerKit board plus our own row logic.

## Variation recipe engine (2026-11-08, Agreed direction)
User asked for a logic-based (not prompt-based) way to vary games. Every
variation is a recipe of a few building blocks (`engine/variants/base.py`):
private cards; board groups (with layout position; a group used by several
rows = shared card); stages (what is burned/revealed before each betting
round); rows (which groups a row uses, how many private cards it may use —
"fix N" or "012…", whether private cards are SHARED between rows or SPLIT
before showdown, optional "one card per group"); scoring ("split" pot per
row, or "best" single row wins all); selection ("auto" best hand, or
"declare" = humans pick their own cards, bots pick best).
Presets with dealer options live in `engine/variants/presets.py`.
PokerKit still does betting, side pots and payouts; we supply hand strength
per row (one PokerKit "hand type" per pot portion; verified in
`research/pokerkit_probe4_custom_scoring.py`).

Engine facts found while building (both fixed + tested):
- PokerKit marks hands "dead" as soon as the board completes — before
  humans declare. Until declarations are in, every player reports the same
  placeholder hand so nobody is killed early; real hands are filled in before
  any chips move (the engine refuses to pay out otherwise).
- Fairness: in variations with showdown choices, NO player's cards are
  revealed until everyone has chosen (found in browser testing: opponents'
  cards were visible while the human was still splitting).

## Variation library — agreed rules (2026-11-08)
Betting rounds everywhere: preflop, flop, turn ("mid"), river ("post river"
in the user's words). No-limit. Burn before each reveal unless noted.
Defaults: buy-in 500, blinds 10/10, chips 10/20/50/100/500/1000.
Before every hand the dealer (vs bots: always the human) picks a preset and
its options. Status = implemented + tested unless noted.

1. **Texas Hold'em** — option "012" (any 5 of 7, classic) or "Fix 2"
   (exactly both private cards + 3 community).
2. **Omaha** — 4 private; default Fix 2 (exactly 2 + 3); option "any".
3. **Double Board Hold'em** — 4 private, two rows of 5. Option SPLIT
   (default: 2 cards to each row before showdown; a card can't play in both)
   or SHARED (cards usable in both rows). Hand rule 012/Fix 2. Pot split half
   per row; win both = whole pot.
4. **Double Board Omaha** — 6 or 8 private; split (3+3 / 4+4) or shared;
   Fix 2 default. 8 cards fits at most 4 players.
5. **Pyramid** — 2 private; rows 5,4,3 (flop), 2 (turn), 1 (river). At most
   one community card from each pyramid row. Hand rule 012/Fix 2. Humans
   pick their own 5 cards at showdown (a weaker pick counts); bots pick best.
6. **Elevator** — 6 private; flop three rows of 3; turn + river shared by
   all rows. Before showdown split 6 cards into 3 pairs (one per row; secret
   until everyone has chosen). Each row: pair + row's 3 + 2 elevator cards,
   rule 012 or Fix 2; best hand in a row is then made automatically from the
   assigned pair. Each row wins 1/3 of each pot (odd chips to first row);
   folding forfeits every row; one shared betting sequence.
7. **Twin Rows** (user's "var 7", name is a placeholder) — 3 private; burn,
   flop 3+3; burn, 1 shared turn; then 1+1 river with NO burn (as dealt by the
   user). Rule 0123 (any 5) default; Fix 2/Fix 3 options. Single pot: each
   player's best row counts; best hand wins everything.
   ASSUMPTION to confirm: "dealt face down" = revealed at its betting round.
8. **2or3** — 5 private; flop top 3 + bottom 2; option "shared turn,
   1+1 river" (default) or "1+1 turn, shared river". Top row: exactly 2
   private; bottom row: exactly 3 private. Single pot, best row wins all.

9. **3or3or2** (2026-11-09) — flop 3+3+2, shared turn, 1+1+1 river.
   ASSUMED by analogy with 2or3 (confirm): 5 private; 3-card-flop rows use
   exactly 2 private, the 2-card-flop row exactly 3; best row wins all.

Rows never mix: a hand uses only its own row's cards plus cards shared by
that row (e.g. a common turn). Verified by tests. (A highlighting bug made
it LOOK mixed when a player had good hands in two rows — fixed: only the
row that won a pot is highlighted.)

## Special cards — any variation (2026-11-09)
Dealer picks None / Joker / Poison / Jumping joker and the stage it is turned
up (flop, turn, river). It is an extra card set apart from the board, in no row.
- Joker: PRIVATE cards of its rank are wild (board cards are not).
- Poison: private cards of its rank can't be used.
- Jumping joker: its rank is poison; ranks one above/below are wild; A is
  next to both K and 2.
- A wild card becomes any card not already in that 5-card hand (so no "five
  of a kind"). If poison leaves no legal hand (e.g. Fix 2), that row has no
  hand and loses to every real hand.
ASSUMPTIONS to confirm: private cards only; no five-of-a-kind; A wraps.

## Human-like bots (2026-11-09, user: "most bots fold in the beginning")
Bots never share information (each gets only its own filtered view). They
folded too much because preflop they compared equity against ALL opponents
with the price to call. Now preflop they judge hand quality on its own
(heads-up strength), with position, raise size, limping, and per-level
looseness; postflop they add sunk-cost calls and short "tilt" after a big loss,
round bet sizes, and take human-like time (quick folds, long all-in thinks).
Measured with tools/bot_stats.py (6 bots, 80 hands): VPIP Noob ~65%,
Amateur ~44%, Tycoon ~33% (was 46/14/13).

Showdown presentation: players reveal one at a time from left of the dealer;
split-pot games get one showdown per part (e.g. Poker, then Teen Patti).
A-K-Q-J-10 suited is labelled "Royal flush".

## Bots (2026-11-09)
Levels: Noob (misreads hands, calls too much), Amateur (sensible),
Tycoon (more simulation, tighter, sizes bets by strength, semi-bluffs).
Chosen at sit-down; "Mixed" seats one of each. All obey the same rules.

## Game families (2026-11-09, user's request to streamline the dealer page)
The dealer picks a FAMILY, then its adjustable parts (engine/variants/families.py):
- Classic board: 5 community; private 2–6; Any / Fix 2 / Fix 3.
  (Hold'em = 2 + any; Omaha = 4 + Fix 2.)
- Double board: two SEPARATE boards, pot split per board; private 4/6/8;
  split or shared private cards; rule.
- Shared-card rows: layouts 3+2 shared turn (2or3), 3+2 shared river,
  3+3+2 shared turn (3or3or2), 3+3 shared turn (Twin Rows), 3+3+3 shared
  turn & river (Elevator). Private cards "classic" or 3–7; rule "classic",
  "5 shown→2 / 4 shown→3", any, Fix 2; pot "classic", best row wins all, or
  split cards & pot per row. User: with shared cards the normal rule is ONE
  pot, best row wins; 3or3or2 needs at least 3 private cards (the 4-card row
  must use 3). Classic Elevator keeps its own rule (split pairs, pot in thirds).
- Pyramid (separate game): private 2–4; Any / Fix 2.
- Personal board (user's "private community cards" game): N private face
  down; 3 common flop; each player's own turn and river dealt FACE UP
  (everyone sees, only the owner uses); any 5.
- Poker Patti: 5 private (Texas: 2 poker + 3 Teen Patti) or 7 (Omaha: 4
  poker with Fix 2 + 3 Teen Patti). Split before showdown; pot half/half.
  Teen Patti ranking (ASSUMED standard, confirm): Trail > Pure sequence >
  Sequence > Color > Pair > High card; A-K-Q top sequence, A-2-3 second.

Add-ons for every family:
- Special card: Joker / Poison / Jumping joker; flop/turn/river; affects
  private cards only (default) or private + community (user: "could be a
  variation").
- Anaconda: after the flop betting (or after every round from the flop),
  everyone still in passes 1 face-down private card to the next player on
  their left. Passed cards are seen only by the receiver; showdown shows
  what each player holds after passing. ASSUMED: face-up personal cards
  can't be passed; folded players don't pass or receive.
- Random: any family + options + (50%) a special card + (25%) Anaconda,
  always one that can be dealt to the current table.

Build-your-own-variation plan: docs/BUILDER_PLAN.md.

Not yet: a "custom" builder form in the
browser (engine already supports it — next step); prompt-driven authoring
(deferred; never needed for gameplay).


## Online rooms (Milestone 3)
- One table per room, 6 seats. Whoever starts the table is the host. Friends join with the 5-letter code or the invite link (`/?room=CODE`).
- Bots and friends mix freely: the host picks 0-5 bots at the start and can add or remove bots between hands. If the table is full, a joining friend replaces a bot between hands.
- Each browser gets a secret token from the server (sessionStorage per tab, localStorage as a fallback). Reconnecting with it gives back the same seat. Tokens are never sent to other players.
- Dealer's choice rotates with the button: the player who will deal the next hand picks the game. If that seat is a bot or offline, the host picks. If the dealer takes more than 45 s, the host may pick for them.
- Turn timer: 30 s to act (check if free, otherwise fold); 60 s for showdown choices and Anaconda passes (best cards / a bot's pass are chosen for you). Offline players get 10 s. Players who left are played instantly.
- Leaving mid-hand folds you out; your seat and chips leave the table when the hand ends. A room closes when everyone has left, or after 30 minutes with nobody connected.
- Going online for free: `Start POKRR online.bat` runs the game plus a Cloudflare quick tunnel (random https link, changes every start, laptop must stay on; the launcher keeps it awake).

## Claiming your hand (every game, from 2026-11-09)
- At every showdown each player claims their own hand: they pick the exact cards. A weaker claim counts, and the "Learn from this hand" panel shows the better choice afterwards. Bots always claim their best.
- In best-row games with several rows (2or3, Twin Rows, Tic-tac-toe, Elevator floors "best floor"), you claim ONE row.
- In split-pot games you claim every part. Leaving a part empty gives that part up; the game asks you to confirm (needed when, for example, poison leaves no legal hand there).
- If time runs out (60 s), the best claim is made for you.
- Engine detail: `TableSettings.claim` (on for every table in the app; off by default in engine tests).

## Learning hints (Settings, all on by default, saved per browser)
- "You have: ..." (your current best; in best-row games just your best row).
- Nuts and second-best possible hand on the current board. Worked out from community cards only (never private cards), with an example 5 cards. "Second-best" means the second-best hand someone could actually end up with (not the nuts with a worse kicker).
- Known limit: a few rare combinations (Tic-tac-toe with a Joker/Jumping-joker card, Elevator floors with 2 private cards) take up to ~1.5 s to compute once per street.

## Elevator floors (agreed 2026-11-09)
- Flop: floors of 1, 2 and 3 cards. Turn and river: 1 card each, shared by all floors.
- Free jokers: floor 1 has 2, floor 2 has 1, floor 3 none (every floor has 5 community items). Jokers are any card, no five of a kind, and always play.
- Hand: at least 2 private cards + the floor's cards/turn/river/jokers, 5 in all.
- ~~Options: private cards 2 / 3 / 4 / 5; pot best floor or split.~~ **Changed 2026-11-10 (owner):** everyone claimed floor 1 for its free jokers, so Floors is now played ONE way only: 6 private cards, split into 3 pairs at showdown (one pair per floor), a claim on each floor, pot split in thirds. Max 6 players (deck size).

## Tic-tac-toe (agreed 2026-11-09)
- 3x3 grid: flop = 4 corners, turn = 4 edges, river = centre.
- Hand: exactly 2 private cards + the 3 cards of one line (3 rows, 3 columns, 2 diagonals). Best line wins the single pot.
- Options: private cards 2 / 3 / 4 (default 4).

## November games (built 2026-11-09)
Rules as the user described them; the points marked (decided) are my calls.
- **Pineapple add-on** (any game with 2+ betting rounds): after a betting round, everyone still in the hand throws away 1 or 2 private cards, face down. Timing: before the flop (classic Pineapple), after the flop (Crazy Pineapple), or every round except the last. 2 cards after the flop with 4 private = Irish poker. It can't be combined with Anaconda (decided). It's refused if too few private cards would remain.
- **Dice add-on** (every game): after the last community card, one die per group of up to 5 community cards (in dealing order). A roll of N replaces the Nth card with a new one; a roll past the end (6) changes nothing. Then one more betting round. The replacement card is dealt by the engine as a hidden card (decided). It can't be combined with Red River (decided).
- **Red River**: a red river means burn, another river, and another betting round, until a black river. There are at most 6 extra rivers (decided; the chain stops there). Hold'em or Omaha (fix 2).
- **Blackjack Hold'em**: 2 private cards. After the flop is dealt (before its betting), each player in order hits or stands. Hit cards are face down (decided). Over 21 = bust: out of the hand and can't win either half. Half the pot to the best poker hand (any 0-2 private cards + board); half to the closest to 21, with a tie going to the better poker hand. Bots hit up to 11, sometimes up to 16.
- **Wall Street**: 3 private cards. A market of 3/4/5 face-up cards. Prices by rank: 2-9 = 1 BB, 10-K = 2 BB, A = 3 BB, paid into the pot. Round-robin from left of the dealer: buy one card or fold, and the market refills at once, until everyone has 3 bought cards. Bought cards are face up. Then one betting round; hand = best 5 of your 6. You must keep at least 1 chip to buy (decided); if you can't afford anything you stop buying. Market money goes to the main-pot winner(s).
- **Short Deck (6+)**: 36 cards; flush beats full house; A-6-7-8-9 is a straight (PokerKit ShortDeckHoldemHand; trips vs straight = standard order).
- **Royal Hold'em**: 20 cards (T-A), standard ranking.
- **Omaha Hi-Lo**: 4 or 5 private, exactly 2 private + 3 board for each half. Low = 8-or-better (A-5 style). No low = high scoops.
- **Courchevel**: Omaha with 5 cards; the first flop card shows before the preflop betting.
- **Iron Cross**: + shaped board (flop left+right, turn top+bottom, river centre). Use the row or the column, at least 2 private (decided). 4 or 5 private.
- **Chowaha** (BARGE rules): 3 flops of 3, 2 turns, 1 river. Exactly 2 private + 3 cards along one connected path (flop → adjacent turn → river; the middle flop touches both turns).
- **7-2 bounty add-on**: a pot winner holding a 7 and a 2 (any suits; decided) collects 5 big blinds from every other player dealt in (as much as each has). The cards are shown.

## More jokers (built 2026-11-10)
One "Wild rule" add-on (choose one), plus the Joker auction. All of these apply to private AND community cards.
- **Deuces wild:** every 2 is wild.
- **One-eyed jacks:** J♠, J♥ and the suicide king K♥ are wild.
- **2 jokers in the deck:** 54 cards. A joker in your hand is your wild card; on the board it's wild for everyone. Not allowed in Blackjack Hold'em (decided: a joker can't be counted toward 21).
- **Follow the Queen:** queens are always wild (decided, as in the classic stud game). When a queen is dealt on the board, the next board card's rank is also wild. A later queen changes it; a queen as the last board card leaves only queens wild.
- **Wild river:** once the river is out, its rank is wild. In Red River the latest river counts.
- **Joker auction:** after the flop betting and before the turn, an English auction, starting left of the dealer. Each bid is at least 1 big blind more; you must keep 1 chip; you can drop out. The winner pays into the pot (won with the main pot) and gets a face-up joker as a wild private card. If nobody bids, there's no joker. Not allowed in games where private cards are split between rows, in Blackjack Hold'em or in Wall Street (decided).
- Jokers carry a dummy rank/suit only for PokerKit's bookkeeping; our rules always treat them as jokers.

## Layout v2 (2026-11-10)
- Three screen shapes, each a canvas shaped like the window: desk (1120 wide), phone sideways (800 wide), phone upright (400 wide). Safe areas (notches) are respected.
- On phones: the header tools are in a ☰ menu; hints sit behind a 💡 tap; the between-hands dialog is two steps (results, then the game picker).
- The dealer's choice uses tabs (Game / Options / Add-ons / Rules) with a summary of the chosen game and add-ons.

## Online launcher fix (2026-11-10)
- A new quick-tunnel link was opened before its address existed, so the router/Windows cached "no such site". The launcher now waits until Cloudflare's DNS knows the link and the link loads, refuses to start a second tunnel on the same port, and keeps one log per port.

## Combination rules (agreed 2026-11-10)
The owner asked to test every game x option x add-on and to prune unintended outcomes.
`tools/combo_audit.py` lists every combination; `engine/table.py: check_combo` enforces these.
- **Wild cards:** at most ONE source per game (wild rule, Joker / Jumping-joker card, or the
  Joker auction). Elevator floors' free jokers count, so Floors takes none. Poison isn't wild.
- **Dice:** only on games with one board of 5 shared cards (Hold'em-style, Courchevel, Hi-Lo,
  Poker Patti, Blackjack Hold'em). Not with Wild river or Follow the Queen.
- **Wild river:** only with exactly one shared river card (not Personal board, whose river is
  private, nor Double board / row games / Red River with several rivers). This was the bug where
  Personal board + Wild river made the 3 flop cards wild.
- **Follow the Queen:** only on boards that are one line of cards.
- **Twists:** at most two of Anaconda, Pineapple, Dice and a game's own twist (Red River's
  extra rivers, Blackjack hits, Wall Street market).
- **Wilds in special scoring:** wild cards help the poker hand only. In the Hi-Lo low, the 21 and
  the Teen Patti hand a wild counts as its printed card, and a joker can't be used there.
- **Special card on Personal board** at the turn/river (no shared card that street): kept.
- **Pineapple:** if too few private cards would be left, the game deals just enough extra private
  cards at the start (only when needed).
- **Deck choice for every game:** Standard 52, Short (6-A, Short Deck ranking: flush beats full
  house, A-6-7-8-9 straight) or Royal (10-A, normal ranking). The separate Short Deck and Royal
  Hold'em games were removed. Deck choices that can't work (too few cards for the players, Hi-Lo
  without low cards) are hidden. Deuces wild and the 7-2 bounty are refused with Short/Royal.
- The picker greys out add-ons that don't fit and lists why.

## Pacing: see what's going on (2026-11-10)
- When one update holds several things (an all-in run-out, a throw-away followed by the next
  cards, a dice roll), the browser shows them one at a time: each street ~1.7 s apart, a thrown
  card flies off before the next cards, the die rolls ~1.5 s, lands, highlights the card it
  replaces, then the new card arrives. Bots wait for it (server/room.py `_pace`).
  Reduced-motion devices get short pauses. Checked by `tools/pace_check.py`.

## Website (2026-11-10)
- `/` home, `/play` the game (old `/?room=` links redirect), `/games` + a page per game (rules
  from the engine), `/learn/hand-rankings`, `/learn/teen-patti-rankings`, `/learn/how-to-play`,
  `/learn/add-ons`, `/about`. `sitemap.xml`, `robots.txt` (all crawlers welcome), `llms.txt` and
  `llms-full.txt` for AI assistants, JSON-LD structured data. Guides work offline once opened
  (web/sw.js). Free, open source (MIT), no ads, no tracking.
