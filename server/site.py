"""The public website around the game: home page, free guides (hand
rankings, Teen Patti rankings, how to play), one page per game, and the
files search engines and AI assistants read (sitemap.xml, robots.txt,
llms.txt). Pages are plain server-rendered HTML: fast, readable without
JavaScript, and cached for offline reading by web/sw.js.

The game rules shown on the game pages come straight from the engine, so
they always match what the table actually does.
"""
from __future__ import annotations

import html
import json
import os
from datetime import date

from engine.table import TableSettings, addon_blocks
from engine.variants import FAMILIES, build_variant

# The site's public address for canonical links, the sitemap and llms.txt.
# Set SITE_URL once you have your own domain; until then each page uses the
# address it was opened on (e.g. the free https://<name>.onrender.com link).
FIXED_URL = os.environ.get("SITE_URL", "").rstrip("/")
SITE_URL = FIXED_URL or "http://localhost:8000"     # replaced per request (see with_base)
NAME = "POKRR"
TAGLINE = "Free poker variations with play chips"
REPO_URL = os.environ.get("REPO_URL", "")
UPDATED = date(2026, 11, 10).isoformat()
ASSET_V = "2"

e = html.escape

# ---------------------------------------------------------------- game intros
# Short, plain descriptions in our own words. The exact rules on each page
# come from the engine (Variant.summary).
INTRO = {
    "classic": ("Texas Hold'em, Omaha and everything in between on one 5-card board.",
                "Pick 2 to 6 private cards and the hand rule: use any of your cards, exactly 2 "
                "(Omaha style) or exactly 3. Two cards with \"any\" is Texas Hold'em; four with "
                "\"exactly 2\" is Omaha."),
    "double": ("Two separate boards, half the pot on each.",
               "Every street deals a card to both boards. At showdown you can win one board, "
               "both, or neither, so a hand that misses on one board can still take half."),
    "rows": ("Rows of flop cards that share a turn and river: 2or3, 3or3or2, Twin Rows and Elevator.",
             "Each row is its own little board. Hands never mix rows. Depending on the layout, the "
             "best row wins the whole pot or you split your cards and the pot row by row."),
    "pyramid": ("A 15-card pyramid: one community card from each level.",
                "The flop opens the three bottom rows at once, the turn the row of two and the "
                "river the top card. Your hand may use at most one card per row, so reading the "
                "pyramid is the whole game."),
    "personal": ("A shared flop, then your OWN face-up turn and river.",
                 "Everyone sees everyone's personal cards, but only the owner can use them. You "
                 "know a lot about your opponents' hands, and they know a lot about yours."),
    "poker_patti": ("Half the pot for poker, half for Teen Patti.",
                    "Split your cards: 2 play Hold'em-style with the board, 3 play as a Teen Patti "
                    "hand on their own. Two different games, one deal."),
    "floors": ("Three floors of 1, 2 and 3 cards, a shared turn and river, and free jokers.",
               "You get 6 private cards and split them into three pairs, one for each floor. "
               "The low floors come with free jokers, so every floor is a real fight, and the pot "
               "is split in thirds."),
    "tictactoe": ("A 3×3 grid of community cards: claim a row, column or diagonal.",
                  "Corners come on the flop, edges on the turn and the centre on the river. Your "
                  "hand is 2 private cards plus the 3 cards of one line."),
    "redriver": ("A red river means another river and another round of betting.",
                 "Hearts or diamonds on the river? Burn, deal one more river and bet again. "
                 "It keeps going until a black card (or six extra rivers)."),
    "hilo": ("Omaha Hi-Lo: the best high hand and the best low hand share the pot.",
             "Use exactly 2 private cards for each half. The low needs five different cards "
             "8 or lower; with no low, the high hand takes it all."),
    "courchevel": ("Five-card Omaha with the first flop card shown before any betting.",
                   "One community card is face up from the start, so the first round of betting "
                   "already has something to read."),
    "ironcross": ("A + shaped board: your hand uses the row or the column.",
                  "Left and right come first, then top and bottom, then the centre, which "
                  "belongs to both lines."),
    "chowaha": ("Three flops lead to two turns, which lead to one river: claim a path.",
                "Your board is one flop, a turn it touches and the river. Choosing the path is "
                "half the fun."),
    "blackjack": ("Poker plus blackjack: half the pot to the best poker hand, half to the closest to 21.",
                  "After the flop everyone can hit or stand. Go over 21 and you're out of the "
                  "hand, so greed has a price."),
    "wallstreet": ("Buy your hand from a market of face-up cards.",
                   "Cards cost chips by rank and the money goes into the pot. Everyone builds a "
                   "6-card hand from 3 private and 3 bought cards."),
}

ADDONS = [
    ("Wild cards", "One kind of wild card per game.", [
        ("Deuces wild", "Every 2, private or community, is wild."),
        ("One-eyed jacks", "J♠, J♥ and the suicide king K♥ are wild."),
        ("Jokers in the deck", "Two jokers are added (54 cards). A joker is any card you need."),
        ("Follow the Queen", "Queens are wild, and so is the rank of the card dealt right after a queen. "
                             "Only on single-line boards."),
        ("Wild river", "Every card of the river's rank is wild. Only where there is exactly one shared river."),
        ("Joker / Poison / Jumping joker card", "An extra card turned up with the flop, turn or river: "
                                                "its rank becomes wild (Joker), dead (Poison), or dead "
                                                "with the ranks either side wild (Jumping joker)."),
        ("Joker auction", "After the flop a face-up joker is auctioned; the winner pays the pot and "
                          "keeps it as a wild private card."),
    ]),
    ("Card swaps", "At most two twists per game (games with a built-in twist count it).", [
        ("Anaconda", "After the flop (or every round), everyone passes 1 private card to the left."),
        ("Pineapple", "Throw away 1 or 2 private cards face down: before the flop, after the flop, "
                      "or every round. 2 after the flop = Irish poker. If too few cards would be "
                      "left, the game deals extra private cards so it still works."),
        ("Dice", "After the river a die picks a community card (1–5) to replace; 6 changes nothing. "
                 "Then one more round of betting. Only on games with one board of 5 cards."),
    ]),
    ("Decks and side bets", "", [
        ("Short deck (6 to A)", "36 cards. A flush beats a full house and A-6-7-8-9 is a straight."),
        ("Royal deck (10 to A)", "20 cards: big hands everywhere. Fits fewer players."),
        ("7-2 bounty", "Win a pot holding a 7 and a 2 and every other player pays you 5 big blinds."),
    ]),
]

COMBO_RULES = [
    "Only one kind of wild card per game. Elevator floors already has free jokers, so it takes no other wild cards. Poison isn't wild, so it can join any game.",
    "Dice only on games with one board of 5 shared cards, and never together with Wild river or Follow the Queen.",
    "Wild river needs exactly one shared river card (not Personal board, Double board, row games or Red River).",
    "Follow the Queen needs a board that is one line of cards.",
    "No Deuces wild or 7-2 bounty with the Short or Royal deck (there are no 2s).",
    "In Hi-Lo, Blackjack Hold'em and Poker Patti, wild cards only help the poker hand: in the low hand, the 21 and the Teen Patti hand they count as their printed card.",
    "At most two card twists at once (Anaconda, Pineapple, Dice, or a game's own twist like Red River's extra rivers).",
]

POKER_RANKS = [
    ("Royal flush", "A K Q J 10 of one suit.", ["As", "Ks", "Qs", "Js", "Ts"], 4),
    ("Straight flush", "Five in a row, all one suit.", ["9h", "8h", "7h", "6h", "5h"], 36),
    ("Four of a kind", "Four cards of one rank.", ["Qc", "Qd", "Qh", "Qs", "4d"], 624),
    ("Full house", "Three of a kind plus a pair.", ["Kd", "Kh", "Ks", "7c", "7d"], 3744),
    ("Flush", "Any five of one suit.", ["Ad", "Jd", "8d", "6d", "2d"], 5108),
    ("Straight", "Five in a row, mixed suits. A can be high or low (A-2-3-4-5).",
     ["Tc", "9d", "8s", "7h", "6c"], 10200),
    ("Three of a kind", "Three cards of one rank.", ["8s", "8h", "8d", "Kc", "3s"], 54912),
    ("Two pair", "Two different pairs.", ["Jh", "Jc", "4s", "4d", "As"], 123552),
    ("One pair", "Two cards of one rank.", ["Th", "Ts", "Ac", "8d", "3h"], 1098240),
    ("High card", "None of the above: the highest card plays.", ["Ah", "Jd", "9c", "6s", "3d"], 1302540),
]
TP_RANKS = [
    ("Trail (three of a kind)", "Three cards of one rank. A-A-A is the best hand.", ["Ah", "Ad", "As"], 52),
    ("Pure sequence", "Three in a row, one suit.", ["Qh", "Jh", "Th"], 48),
    ("Sequence", "Three in a row, mixed suits. A-K-Q is the top sequence, A-2-3 the second.",
     ["Ac", "2d", "3s"], 720),
    ("Color", "Three of one suit, not in a row.", ["Kd", "9d", "4d"], 1096),
    ("Pair", "Two cards of one rank.", ["7s", "7c", "Ah"], 3744),
    ("High card", "None of the above.", ["Ks", "Jh", "6c"], 16440),
]

SUIT = {"s": ("♠", "b"), "c": ("♣", "b"), "h": ("♥", "r"), "d": ("♦", "r")}


def card(code: str) -> str:
    r, s = code[0], code[1]
    sym, col = SUIT[s]
    r = "10" if r == "T" else r
    return f'<span class="pc {col}" aria-label="{r}{sym}">{r}<i>{sym}</i></span>'


def cards(codes) -> str:
    return '<span class="pcs">' + "".join(card(c) for c in codes) + "</span>"


# ---------------------------------------------------------------- page shell
def page(path: str, title: str, desc: str, body: str, *, crumbs=(), extra_ld=()) -> str:
    url = SITE_URL + path
    lds = [{"@context": "https://schema.org", "@type": "WebPage", "name": title,
            "description": desc, "url": url, "dateModified": UPDATED,
            "isPartOf": {"@type": "WebSite", "name": NAME, "url": SITE_URL + "/"}}]
    if crumbs:
        items = [("Home", "/")] + list(crumbs)
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList",
                    "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n,
                                         "item": SITE_URL + p} for i, (n, p) in enumerate(items)]})
    lds += list(extra_ld)
    ld = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>'
                   for x in lds)
    crumb_html = ""
    if crumbs:
        crumb_html = ('<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a>' +
                      "".join(f' › <a href="{p}">{e(n)}</a>' for n, p in crumbs[:-1]) +
                      f' › <span>{e(crumbs[-1][0])}</span></nav>')
    full_title = title if title.startswith(NAME) else f"{title} | {NAME}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE_URL}/static/icon-512.png">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#000000">
<link rel="manifest" href="/static/manifest.webmanifest">
<link rel="icon" type="image/png" href="/static/icon-192.png">
<link rel="apple-touch-icon" href="/static/icon-180.png">
<link rel="alternate" type="text/plain" title="LLM summary" href="/llms.txt">
<link rel="stylesheet" href="/static/site.css?v={ASSET_V}">
{ld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="/">POKRR</a>
  <nav aria-label="Main">
    <a href="/games">Games</a>
    <a href="/learn/hand-rankings">Rankings</a>
    <a href="/learn/how-to-play">How to play</a>
    <a class="cta" href="/play">Play free</a>
  </nav>
</header>
<main id="main">
{crumb_html}
{body}
</main>
<footer>
  <p><b>POKRR</b> is free and open source. Play chips only: no real money, no
  payments, no ads, no sign-up. For fun and learning.</p>
  <p><a href="/">Home</a> · <a href="/games">All games</a> · <a href="/learn/add-ons">Add-ons</a> ·
  <a href="/learn/hand-rankings">Poker hand rankings</a> ·
  <a href="/learn/teen-patti-rankings">Teen Patti rankings</a> ·
  <a href="/learn/how-to-play">How to play</a> · <a href="/about">About</a>{
  f' · <a href="{e(REPO_URL)}" rel="noopener">Source code</a>' if REPO_URL else ''}</p>
</footer>
<script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {{}});</script>
</body>
</html>"""


# ---------------------------------------------------------------- game data
def default_variant(fid):
    fam = FAMILIES[fid]
    return build_variant(fid, {o.key: o.default for o in fam.options})


def fitting_addons(fid) -> tuple[list[str], list[str]]:
    """(add-ons that fit this game, ones that don't) with the default options."""
    st = TableSettings(500, 10, 10, fid, tuple(sorted(
        (o.key, o.default) for o in FAMILIES[fid].options)), claim=True)
    blocks = addon_blocks(st, 3)
    names = {("wild", "deuces"): "Deuces wild", ("wild", "oneeyed"): "One-eyed jacks",
             ("wild", "jokers"): "Jokers in the deck", ("wild", "queen"): "Follow the Queen",
             ("wild", "river"): "Wild river", ("special_kind", "joker"): "Joker card",
             ("special_kind", "poison"): "Poison card", ("special_kind", "jumping"): "Jumping joker",
             ("auction", "true"): "Joker auction", ("anaconda", "flop"): "Anaconda",
             ("pineapple", "preflop"): "Pineapple", ("dice", "true"): "Dice",
             ("bounty", "true"): "7-2 bounty", ("deck", "short"): "Short deck",
             ("deck", "royal"): "Royal deck"}
    yes, no = [], []
    for (f, v), label in names.items():
        (no if v in blocks.get(f, {}) else yes).append(label)
    return yes, no


def game_slug(fid: str) -> str:
    return fid.replace("_", "-")


# ---------------------------------------------------------------- pages
def home() -> str:
    tiles = "".join(
        f'<a class="tile" href="/games/{game_slug(fid)}"><b>{e(f.name)}</b>'
        f'<span>{e(INTRO.get(fid, (f.pitch,))[0])}</span></a>'
        for fid, f in FAMILIES.items())
    faq = [
        ("Is POKRR free?", "Yes, completely. POKRR uses play chips only: no real money, no payments, "
                           "no ads and no sign-up. It is free and open source."),
        ("Can I play poker with friends online?", "Yes. Start a table, tap Invite friends and send "
                                                  "the link or the 5-letter table code. Add bots to fill empty seats."),
        ("Can I play alone?", "Yes. Start a table with 1 to 5 bots at three levels: Noob, Amateur and Tycoon."),
        ("Which poker games can I play?", "Texas Hold'em, Omaha, Omaha Hi-Lo, Pineapple, Short Deck and "
                                          "many unusual games such as Pyramid, Elevator floors, Tic-tac-toe "
                                          "poker, Red River, Chowaha, Iron Cross, Blackjack Hold'em, Wall "
                                          "Street and Poker Patti. Add wild cards, dice, Anaconda passing "
                                          "and more: over 5 lakh (500,000+) game combinations."),
        ("Does it work on phones?", "Yes. POKRR runs in any modern browser on phones, tablets and "
                                    "computers, upright or sideways. Add it to your home screen to "
                                    "open it like an app."),
        ("Who chooses the game?", "Dealer's choice: the dealer button moves round the table, and whoever "
                                  "has it picks the next game and its add-ons."),
    ]
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in faq]}
    app_ld = {"@context": "https://schema.org", "@type": "WebApplication", "name": NAME,
              "url": SITE_URL + "/play", "applicationCategory": "GameApplication",
              "genre": "Card game", "operatingSystem": "Any (web browser)",
              "offers": {"@type": "Offer", "price": "0", "priceCurrency": "INR"},
              "isAccessibleForFree": True,
              "description": "Free browser poker with play chips: Texas Hold'em, Omaha and dozens "
                             "of variations with friends or bots. No money, no ads, no sign-up."}
    site_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": NAME,
               "url": SITE_URL + "/", "description": TAGLINE}
    body = f"""
<section class="hero">
  <h1>Free poker variations, <span>play chips only</span></h1>
  <p class="lead">POKRR is a free, open-source poker table in your browser. Play Texas Hold'em,
  Omaha and more than a dozen unusual poker games with friends or bots. No money, no ads, no
  sign-up.</p>
  <p><a class="btn" href="/play">Play now, free</a>
     <a class="btn ghost" href="/learn/how-to-play">New to poker? Start here</a></p>
  <ul class="facts">
    <li><b>15</b> game families</li>
    <li><b>500,000+</b> game combinations</li>
    <li><b>2–6</b> players + bots</li>
    <li><b>0</b> real money</li>
  </ul>
</section>

<section>
  <h2>How it works</h2>
  <ol class="steps">
    <li><b>Start a table.</b> Pick a name, how many bots (0–5) and their level.</li>
    <li><b>Invite friends.</b> Share the link or the 5-letter table code. Anyone with the link can join.</li>
    <li><b>Dealer's choice.</b> The dealer picks the game, its options and add-ons for each hand.</li>
    <li><b>Claim your hand.</b> At showdown you pick your own cards. A weaker claim counts, so read carefully!</li>
  </ol>
</section>

<section>
  <h2>The games</h2>
  <div class="tiles">{tiles}</div>
  <p><a href="/learn/add-ons">Add-ons</a>: wild cards, jokers, Anaconda, Pineapple, dice, the
  Joker auction, Short and Royal decks and the 7-2 bounty, which you can mix into most games.</p>
</section>

<section>
  <h2>Free poker guides</h2>
  <ul class="links">
    <li><a href="/learn/hand-rankings">Poker hand rankings</a>, from royal flush to high card, with odds.</li>
    <li><a href="/learn/teen-patti-rankings">Teen Patti hand rankings</a>: trail, pure sequence, sequence, color, pair.</li>
    <li><a href="/learn/how-to-play">How to play poker</a>: blinds, betting rounds, showdown and side pots.</li>
    <li><a href="/learn/add-ons">Poker add-ons</a> and which ones fit which games.</li>
  </ul>
  <p class="muted">The guides also work offline once you've opened them.</p>
</section>

<section>
  <h2>Questions</h2>
  {"".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)}
</section>
"""
    return page("/", f"{NAME}: free poker variations with play chips",
                "Play free poker in your browser with play chips: Texas Hold'em, Omaha and dozens of "
                "variations like Pyramid, Elevator and Tic-tac-toe poker, with friends or bots. No "
                "money, no ads, no sign-up.", body, extra_ld=(site_ld, app_ld, faq_ld))


def games_index() -> str:
    rows = "".join(
        f'<a class="tile" href="/games/{game_slug(fid)}"><b>{e(f.name)}</b>'
        f'<span>{e(INTRO.get(fid, (f.pitch,))[0])}</span></a>' for fid, f in FAMILIES.items())
    body = f"""<h1>Poker variations</h1>
<p class="lead">Every game on POKRR, with its exact rules. Each one can be changed with options
(cards, hand rule, pot) and <a href="/learn/add-ons">add-ons</a>.</p>
<div class="tiles">{rows}</div>"""
    return page("/games", "All poker variations",
                "Rules for every poker variation on POKRR: Hold'em, Omaha, Hi-Lo, Pyramid, Elevator "
                "floors, Tic-tac-toe, Red River, Chowaha, Iron Cross, Blackjack Hold'em, Wall Street "
                "and more.", body, crumbs=(("Games", "/games"),))


def game_page(fid: str) -> str:
    fam = FAMILIES[fid]
    v = default_variant(fid)
    one, more = INTRO.get(fid, (fam.pitch, ""))
    opts = "".join(
        f"<li><b>{e(o.label)}:</b> " + ", ".join(e(c[1]) for c in o.choices) + "</li>"
        for o in fam.options) or "<li>No options: it's always played this way.</li>"
    yes, no = fitting_addons(fid)
    others = "".join(f'<li><a href="/games/{game_slug(g)}">{e(f.name)}</a></li>'
                     for g, f in FAMILIES.items() if g != fid)
    body = f"""<h1>{e(fam.name)}</h1>
<p class="lead">{e(one)}</p>
<p>{e(more)}</p>
<h2>Rules ({e(v.name)})</h2>
<ul class="rules">{"".join(f"<li>{e(x)}</li>" for x in v.summary)}</ul>
<p class="muted">Betting is no-limit with small and big blinds. At showdown you claim your own
cards; a weaker claim counts.</p>
<h2>Options</h2>
<ul>{opts}</ul>
<h2>Add-ons</h2>
<p><b>Fit this game:</b> {e(", ".join(yes)) or "none"}.</p>
{f"<p><b>Not with this game:</b> {e(', '.join(no))}. <a href='/learn/add-ons#rules'>Why?</a></p>" if no else ""}
<p><a class="btn" href="/play">Play {e(fam.name)} free</a></p>
<h2>More games</h2>
<ul class="cols">{others}</ul>"""
    desc = f"{fam.name} poker rules: {one} Play it free with friends or bots on POKRR (play chips only)."
    game_ld = {"@context": "https://schema.org", "@type": "Game", "name": f"{fam.name} (poker variation)",
               "description": one, "url": f"{SITE_URL}/games/{game_slug(fid)}",
               "gameItem": "Standard 52-card deck", "numberOfPlayers": {
                   "@type": "QuantitativeValue", "minValue": 2, "maxValue": min(6, v.max_players)}}
    return page(f"/games/{game_slug(fid)}", f"{fam.name} poker: rules and how to play", desc, body,
                crumbs=(("Games", "/games"), (fam.name, f"/games/{game_slug(fid)}")),
                extra_ld=(game_ld,))


def rankings() -> str:
    total = 2598960
    rows = "".join(
        f"<tr><td>{i + 1}</td><td><b>{e(n)}</b><br><span class='muted'>{e(d)}</span></td>"
        f"<td>{cards(c)}</td><td>{k:,} <span class='muted'>({k / total * 100:.4g}%)</span></td></tr>"
        for i, (n, d, c, k) in enumerate(POKER_RANKS))
    body = f"""<h1>Poker hand rankings</h1>
<p class="lead">From best to worst. A poker hand is always exactly five cards; when two hands
are the same type, the higher cards win (a pair of kings beats a pair of queens; with the same
pair, the next-highest card, the "kicker", decides).</p>
<div class="table-wrap"><table class="ranks">
<thead><tr><th>#</th><th>Hand</th><th>Example</th><th>Ways to make it<br>(out of 2,598,960)</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<h2>Good to know</h2>
<ul>
<li><b>Suits are equal.</b> No suit beats another. Two equal hands split the pot.</li>
<li><b>Ace high or low.</b> A-K-Q-J-10 is the top straight and 5-4-3-2-A the lowest (the "wheel"). A straight can't wrap round (Q-K-A-2-3 is not a straight).</li>
<li><b>Wild cards</b> can be any card you need. On POKRR they can't make five of a kind.</li>
<li><b>Short deck (6 to A):</b> a flush beats a full house, and A-6-7-8-9 is the lowest straight.</li>
<li><b>Low hands (Hi-Lo):</b> five different cards 8 or lower; A-2-3-4-5 is the best low, and straights and flushes don't count against it.</li>
</ul>
<p>Also see <a href="/learn/teen-patti-rankings">Teen Patti rankings</a> (3-card hands) and
<a href="/learn/how-to-play">how to play</a>.</p>"""
    return page("/learn/hand-rankings", "Poker hand rankings (with odds)",
                "Poker hand rankings from best to worst: royal flush, straight flush, four of a kind, "
                "full house, flush, straight, three of a kind, two pair, pair and high card, with "
                "examples and odds.", body,
                crumbs=(("Learn", "/learn/how-to-play"), ("Hand rankings", "/learn/hand-rankings")))


def tp_rankings() -> str:
    total = 22100
    rows = "".join(
        f"<tr><td>{i + 1}</td><td><b>{e(n)}</b><br><span class='muted'>{e(d)}</span></td>"
        f"<td>{cards(c)}</td><td>{k:,} <span class='muted'>({k / total * 100:.3g}%)</span></td></tr>"
        for i, (n, d, c, k) in enumerate(TP_RANKS))
    body = f"""<h1>Teen Patti hand rankings</h1>
<p class="lead">Teen Patti ("three cards") is played with 3-card hands. From best to worst:</p>
<div class="table-wrap"><table class="ranks">
<thead><tr><th>#</th><th>Hand</th><th>Example</th><th>Ways to make it<br>(out of 22,100)</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<h2>Good to know</h2>
<ul>
<li><b>Sequences:</b> A-K-Q is the highest, A-2-3 the second highest, then K-Q-J down to 4-3-2.</li>
<li><b>Same type:</b> compare the highest card, then the next. For pairs, the pair first, then the third card.</li>
<li>In 3 cards a sequence is rarer than a color, so it ranks higher (unlike 5-card poker).</li>
<li>On POKRR, Teen Patti hands appear in <a href="/games/poker-patti">Poker Patti</a>: 3 of your cards play as a Teen Patti hand for half the pot.</li>
</ul>"""
    return page("/learn/teen-patti-rankings", "Teen Patti hand rankings (with odds)",
                "Teen Patti hand rankings from best to worst: trail, pure sequence, sequence, color, "
                "pair and high card, with examples and the odds of each 3-card hand.", body,
                crumbs=(("Learn", "/learn/how-to-play"), ("Teen Patti rankings", "/learn/teen-patti-rankings")))


def how_to_play() -> str:
    body = """<h1>How to play poker</h1>
<p class="lead">The basics of Texas Hold'em, the game most variations build on. Ten minutes to
learn, a lifetime to master.</p>
<h2>1. The deal</h2>
<p>Each player gets 2 private cards (face down). Five community cards will be dealt face up in
the middle, and everyone can use them. Your hand is the best five cards from your 2 and the 5 on
the board.</p>
<h2>2. Blinds</h2>
<p>Before the cards, the two players to the left of the dealer button put in forced bets: the
<b>small blind</b> and the <b>big blind</b>. They give everyone something to play for. The button
moves one seat to the left after each hand.</p>
<h2>3. Four rounds of betting</h2>
<ol>
<li><b>Preflop:</b> after the private cards. The player left of the big blind acts first.</li>
<li><b>Flop:</b> three community cards, then betting.</li>
<li><b>Turn:</b> a fourth card, then betting.</li>
<li><b>River:</b> the fifth card, then the last betting round.</li>
</ol>
<p>On your turn you can:</p>
<ul>
<li><b>Fold:</b> give up the hand.</li>
<li><b>Check:</b> pass without betting (only when no one has bet).</li>
<li><b>Call:</b> match the current bet.</li>
<li><b>Bet / Raise:</b> put in chips, or more than the current bet. In no-limit you can bet anything up to all your chips.</li>
<li><b>All-in:</b> bet everything you have.</li>
</ul>
<h2>4. Showdown</h2>
<p>If two or more players are left after the river, they show their cards and the best five-card
hand wins the pot (see <a href="/learn/hand-rankings">hand rankings</a>). Equal hands split it.
On POKRR you <b>claim your own hand</b> by picking the cards, and a weaker claim counts.</p>
<h2>5. Side pots</h2>
<p>If a player is all-in and others keep betting, the extra chips go into a side pot that the
all-in player can't win. Each pot goes to the best hand among the players in it.</p>
<h2>Variations</h2>
<p>Change the number of private cards, how many you must use, or the shape of the board, and you
get a new game: <b>Omaha</b> (4 cards, use exactly 2), <b>Pineapple</b> (throw cards away),
<b>Pyramid</b>, <b>Elevator</b> and many more. See <a href="/games">all games</a>.</p>
<h2>Words you'll hear</h2>
<dl class="gloss">
<dt>Nuts</dt><dd>The best possible hand with the cards on the board.</dd>
<dt>Kicker</dt><dd>The highest side card, which breaks ties between equal pairs or sets.</dd>
<dt>Burn</dt><dd>A card put away face down before each new street.</dd>
<dt>Wild card</dt><dd>A card that can stand for any card.</dd>
<dt>Button</dt><dd>The dealer marker. The player on it acts last after the flop.</dd>
</dl>
<p><a class="btn" href="/play">Practise against bots, free</a></p>"""
    return page("/learn/how-to-play", "How to play poker: a beginner's guide",
                "Learn to play poker in 10 minutes: the deal, blinds, the four betting rounds, fold, "
                "check, call and raise, showdown and side pots. Then practise free against bots.",
                body, crumbs=(("Learn", "/learn/how-to-play"), ("How to play", "/learn/how-to-play")),
                extra_ld=({"@context": "https://schema.org", "@type": "HowTo",
                           "name": "How to play Texas Hold'em poker",
                           "step": [{"@type": "HowToStep", "name": n, "text": t} for n, t in (
                               ("The deal", "Each player gets 2 private cards; 5 community cards are shared."),
                               ("Blinds", "The two players left of the button post the small and big blind."),
                               ("Betting rounds", "Bet preflop, after the flop (3 cards), the turn and the river."),
                               ("Showdown", "The best five-card hand from your cards and the board wins."))]},))


def addons_page() -> str:
    parts = []
    for title, note, items in ADDONS:
        parts.append(f"<h2>{e(title)}</h2>" + (f"<p class='muted'>{e(note)}</p>" if note else "") +
                     "<dl class='gloss'>" + "".join(f"<dt>{e(n)}</dt><dd>{e(d)}</dd>" for n, d in items)
                     + "</dl>")
    body = f"""<h1>Poker add-ons</h1>
<p class="lead">Add-ons change a game without changing its board. The dealer can add them to most
games, and POKRR blocks the mixes that would make no sense.</p>
{"".join(parts)}
<h2 id="rules">Which add-ons fit together</h2>
<ul>{"".join(f"<li>{e(r)}</li>" for r in COMBO_RULES)}</ul>
<p>Each <a href="/games">game page</a> lists the add-ons that fit it.</p>"""
    return page("/learn/add-ons", "Poker add-ons: wild cards, jokers, Pineapple, Anaconda, dice",
                "How poker add-ons work on POKRR: deuces wild, one-eyed jacks, jokers, Follow the "
                "Queen, wild river, Anaconda, Pineapple, dice, the Joker auction, Short and Royal "
                "decks and the 7-2 bounty.", body,
                crumbs=(("Learn", "/learn/how-to-play"), ("Add-ons", "/learn/add-ons")))


def about() -> str:
    src = (f'<p>The full source code is on <a href="{e(REPO_URL)}" rel="noopener">GitHub</a> '
           'under the MIT licence. Suggestions and fixes are welcome.</p>' if REPO_URL else
           "<p>POKRR is open source under the MIT licence.</p>")
    body = f"""<h1>About POKRR</h1>
<p class="lead">POKRR is a free poker table for friends who like to try new games.</p>
<h2>Play chips only</h2>
<p>There is no real money anywhere in POKRR: no buying chips, no prizes, no payments, no
gambling. Chips are just for keeping score, and you can rebuy for free at any time.</p>
<h2>No ads, no tracking, no sign-up</h2>
<p>POKRR shows no ads and uses no analytics or tracking. You don't need an account: your seat is
kept by a random code stored in your own browser. Tables are deleted when everyone leaves.</p>
<h2>Fair dealing</h2>
<p>Cards are shuffled on the server with a cryptographically secure random generator. Your
browser only ever receives your own private cards, never anyone else's or the deck.</p>
<h2>Open source</h2>
{src}"""
    return page("/about", "About POKRR: free, open source, play chips only",
                "POKRR is a free, open-source poker game: play chips only, no ads, no tracking, no "
                "sign-up, secure shuffling.", body, crumbs=(("About", "/about"),))


# ---------------------------------------------------------------- machine-readable files
PAGES = {"/": home, "/games": games_index, "/learn/hand-rankings": rankings,
         "/learn/teen-patti-rankings": tp_rankings, "/learn/how-to-play": how_to_play,
         "/learn/add-ons": addons_page, "/about": about}
for _fid in FAMILIES:
    PAGES[f"/games/{game_slug(_fid)}"] = (lambda f=_fid: game_page(f))


def sitemap() -> str:
    urls = ["/play"] + list(PAGES)
    body = "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{UPDATED}</lastmod></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n')


def robots() -> str:
    # everyone (search engines and AI assistants) may read the site; the
    # game socket isn't a page
    return f"User-agent: *\nAllow: /\nDisallow: /ws\n\nSitemap: {SITE_URL}/sitemap.xml\n"


def llms_txt(full: bool = False) -> str:
    """Plain-text summary for AI assistants (https://llmstxt.org)."""
    out = [f"# {NAME}", "",
           "> POKRR is a free, open-source poker game in the browser with play chips only (no real "
           "money, no ads, no sign-up). Play Texas Hold'em, Omaha and many poker variations with "
           "friends (share a link or a 5-letter table code) or with bots.", "",
           "Key facts:",
           f"- Play: {SITE_URL}/play (any modern browser; phones, tablets, computers)",
           "- Price: free. Play chips only; no payments, prizes or gambling.",
           "- Players: 2 to 6 per table, people and bots (levels Noob, Amateur, Tycoon).",
           "- Dealer's choice: the dealer picks the game and add-ons each hand.",
           "- Showdown: players claim their own 5-card hand; a weaker claim counts.",
           "- Over 500,000 game combinations (games x options x add-ons x decks; 512,536 counted by tools/count_combos.py).", "",
           "## Guides",
           f"- [Poker hand rankings]({SITE_URL}/learn/hand-rankings): best to worst, with odds",
           f"- [Teen Patti hand rankings]({SITE_URL}/learn/teen-patti-rankings): 3-card hands",
           f"- [How to play poker]({SITE_URL}/learn/how-to-play): blinds, betting, showdown, side pots",
           f"- [Add-ons]({SITE_URL}/learn/add-ons): wild cards, Anaconda, Pineapple, dice, decks",
           f"- [About]({SITE_URL}/about): play chips only, no tracking, open source", "",
           "## Games"]
    for fid, fam in FAMILIES.items():
        out.append(f"- [{fam.name}]({SITE_URL}/games/{game_slug(fid)}): {INTRO.get(fid, (fam.pitch,))[0]}")
        if full:
            v = default_variant(fid)
            out += [f"  - {x}" for x in v.summary]
    if full:
        out += ["", "## Add-ons"]
        for title, note, items in ADDONS:
            out += [f"### {title}"] + [f"- {n}: {d}" for n, d in items]
        out += ["", "## Which add-ons fit together"] + [f"- {r}" for r in COMBO_RULES]
        out += ["", "## Poker hand rankings (best first)"] + [f"{i + 1}. {n}: {d}" for i, (n, d, _, _) in
                                                              enumerate(POKER_RANKS)]
        out += ["", "## Teen Patti rankings (best first)"] + [f"{i + 1}. {n}: {d}" for i, (n, d, _, _) in
                                                              enumerate(TP_RANKS)]
    else:
        out += ["", "## Optional", f"- [Full rules in one file]({SITE_URL}/llms-full.txt)"]
    return "\n".join(out) + "\n"


# Built once per address (the content only changes with a deploy).
CACHE: dict[tuple, str] = {}


def with_base(base: str, fn, *args):
    """Run ``fn`` with SITE_URL = the fixed address, or else ``base`` (the
    address this request came in on). Pages are built synchronously, so the
    module-level value can't leak between requests."""
    global SITE_URL
    SITE_URL = FIXED_URL or base.rstrip("/")
    return fn(*args)


def render(path: str, base: str = "") -> str | None:
    if path not in PAGES:
        return None
    key = (FIXED_URL or base, path)
    if key not in CACHE:
        CACHE[key] = with_base(base, PAGES[path])
    return CACHE[key]
