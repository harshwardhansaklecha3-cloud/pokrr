# POKRR

**Free poker variations in your browser. Play chips only: no real money, no ads, no sign-up.**

Play Texas Hold'em, Omaha and more than a dozen unusual poker games with friends (share a
link or a 5-letter table code) or with bots. The dealer picks the game every hand, and
add-ons (wild cards, jokers, Anaconda, Pineapple, dice, Short/Royal decks…) give over
500,000 combinations (512,536 counted).

Play it: <https://pokrr.onrender.com> (free hosting; the first visit after a quiet spell takes ~1 minute to wake up)

## Games
Classic board (Hold'em / Omaha / any number of cards), Double board, Shared-card rows (2or3,
3or3or2, Twin Rows, Elevator), Pyramid, Personal board, Poker Patti, Elevator floors,
Tic-tac-toe, Red River, Omaha Hi-Lo, Courchevel, Iron Cross, Chowaha, Blackjack Hold'em and
Wall Street. Rules for each are on the website (`/games`) and in `docs/DECISIONS.md`.

## Principles
- **Play chips only.** No payments, prizes or gambling of any kind.
- **The server is the dealer.** Secure shuffle (`secrets.SystemRandom`); each browser only
  ever receives its own private cards. Bots see only their own view.
- **Every action is checked.** Illegal, stale and duplicate actions are rejected; chips are
  always conserved (tested on every action in long random games).
- **No tracking.** No accounts, analytics or ads.

## Run it on your computer
Needs Python 3.12+ (tested on 3.14).

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt      (Windows)
    .venv/bin/python -m pip install -r requirements.txt              (Mac/Linux)

    .venv\Scripts\python.exe -m uvicorn server.app:app --port 8000

Open <http://localhost:8000> (website) or <http://localhost:8000/play> (the game).
On Windows you can also double-click `Start POKRR.bat`.

## Tests

    .venv\Scripts\python.exe -m pytest -q                 # rules, server, website (~6 min)
    .venv\Scripts\python.exe tools\combo_audit.py --quick  # every game x add-on combination
    .venv\Scripts\python.exe tools\ui_check.py             # 7 screen sizes (needs Playwright)
    .venv\Scripts\python.exe tools\pace_check.py           # deals/dice/throw-aways shown one at a time

## Layout
| Folder | What it holds |
|---|---|
| `engine/` | Rules: deck, one hand on [PokerKit](https://github.com/uoftcprg/pokerkit), the table, hints |
| `engine/variants/` | Game families, options and add-ons |
| `bots/` | Bots (they see only their own view) |
| `server/` | FastAPI app: WebSocket rooms (`room.py`) and the website (`site.py`) |
| `web/` | The game page and website styles (plain HTML/CSS/JS, no build step) |
| `tests/` | Engine, add-on combinations, soak, server and website tests |
| `tools/` | Combination audit, screen checks, the "online with a Cloudflare link" launcher |
| `docs/` | Plans and the decision log (`DECISIONS.md`: every agreed rule) |

## Hosting
`render.yaml` deploys a free [Render](https://render.com) web service that redeploys on every
push to `main`. Set `SITE_URL` to your domain. The free plan sleeps after 15 idle minutes
(the first visit then takes about a minute), and open tables reset on a redeploy.

## Licence
MIT. Built on PokerKit (MIT).
