"""Rooms: one table shared by friends, plus any bots the host adds.

* Someone starts a table and becomes the **host**. The room gets a short
  code (e.g. ``K7QXM``); friends join with the code or the invite link.
* Every browser has a secret **token** (made by the server, kept in the
  browser). Reloading or reconnecting with it gives you your seat back.
  Tokens are never sent to anyone else.
* **Dealer's choice rotates with the button**: the player who will deal the
  next hand picks the game. If that seat is a bot (or the player is offline)
  the host picks. If the dealer takes too long, the host may pick for them.
* **Turn timers**: 30 s to act, 60 s for showdown choices / Anaconda passes.
  When time runs out you check if free, otherwise fold; showdown choices and
  passes are made for you (best cards / the card a bot would pass).
  Players who are offline get 10 s; players who left are played instantly.
* Players who leave mid-hand are folded out and removed when the hand ends.
  If the table is full, a friend who joins replaces a bot between hands.
"""
from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from bots import LEVEL_LABELS, LEVELS, BasicBot
from engine.hand import IllegalAction
from engine.table import Table, TableSettings, preview_choice, random_choice
from engine.variants import VariantError

log = logging.getLogger("poker.room")

BOT_NAMES = ["Ada", "Bram", "Cleo", "Dev", "Esme", "Finn", "Gus", "Hana", "Ivo"]
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0/O, 1/I lookalikes
SEATS = 6
MAX_ROOMS = 300
IDLE_CLOSE = 30 * 60          # a room nobody is connected to closes after 30 min
ERRORS = (IllegalAction, VariantError, ValueError, KeyError, TypeError)


def _int(msg, key, default):
    v = msg.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f"{key} must be a number")
    return int(v)


def clean_name(name) -> str:
    name = " ".join(str(name or "").split())[:16]
    return name or "Player"


@dataclass(eq=False)
class Player:
    token: str
    name: str
    seat: int | None = None          # None while waiting for a free seat
    sockets: set = field(default_factory=set)
    left: bool = False               # left mid-hand: removed when the hand ends
    offline_since: float | None = None

    @property
    def online(self) -> bool:
        return bool(self.sockets)


class GameRoom:
    def __init__(self, code: str, settings: TableSettings, *, bot_delay: float = 0.9,
                 deal_pause: float = 1.6, turn_time: float = 30, choose_time: float = 60,
                 offline_time: float = 10, dealer_wait: float = 45):
        self.code = code
        self.bot_delay, self.deal_pause = bot_delay, deal_pause
        self.turn_time, self.choose_time = turn_time, choose_time
        self.offline_time, self.dealer_wait = offline_time, dealer_wait
        self.lock = asyncio.Lock()
        self.table = Table(seat_count=SEATS, settings=settings)
        self.bots: dict[int, BasicBot] = {}
        self.players: dict[str, Player] = {}
        self.host: str | None = None
        self.queue: list[str] = []                 # tokens waiting for a seat
        self.closed = False
        self.last_active = time.monotonic()
        self._deadlines: dict[tuple, tuple[float, float]] = {}   # wait -> (deadline, total)
        self._bot_task: asyncio.Task | None = None
        self._timer_task: asyncio.Task | None = None
        self._not_before = 0.0
        self._story_seen = (0, 0)              # (hand number, history items already paced)
        self._hurry = False
        self._choose_since = time.monotonic()
        self._done_seen = 0

    # ------------------------------------------------------------ people
    def humans(self) -> dict[int, Player]:
        return {p.seat: p for p in self.players.values() if p.seat is not None}

    def _unique_name(self, name: str) -> str:
        used = {s.name for s in self.table.seats if s} | {p.name for p in self.players.values()}
        if name not in used:
            return name
        for k in range(2, 99):
            cand = f"{name[:13]} {k}"
            if cand not in used:
                return cand
        return name

    def add_bot(self, level: str) -> int:
        if level not in LEVELS:
            raise ValueError("bot level must be noob, amateur or tycoon")
        seat = next((i for i, s in enumerate(self.table.seats) if s is None), None)
        if seat is None:
            raise IllegalAction("the table is full (6 seats)")
        used = {s.name for s in self.table.seats if s}
        name = next((n for n in BOT_NAMES if n not in used), f"Bot {seat + 1}")
        self.table.sit(seat, name, is_bot=True, bot_level=LEVEL_LABELS[level])
        self.bots[seat] = BasicBot(level=level)
        return seat

    def remove_bot(self, seat: int) -> None:
        if seat not in self.bots:
            raise ValueError("that seat is not a bot")
        self.table.stand(seat)              # refuses while the bot is in a hand
        del self.bots[seat]

    def join(self, token: str, name: str) -> Player:
        """Seat a new player (or welcome back one who is already here)."""
        p = self.players.get(token)
        if p is not None:
            p.left = False
            return p
        if len(self.players) >= SEATS:
            raise IllegalAction("this table is full (6 players)")
        p = Player(token, self._unique_name(clean_name(name)))
        self.players[token] = p
        if self.host is None:
            self.host = token
        self.queue.append(token)
        self._seat_queue()
        if p.seat is None and not any(s is None for s in self.table.seats) and not self.bots:
            del self.players[token]
            self.queue.remove(token)
            raise IllegalAction("this table is full (6 players)")
        return p

    def _seat_queue(self) -> None:
        """Give waiting players a seat: an empty one, or a bot's (between hands)."""
        while self.queue:
            p = self.players.get(self.queue[0])
            if p is None:
                self.queue.pop(0)
                continue
            seat = next((i for i, s in enumerate(self.table.seats) if s is None), None)
            if seat is None and self.bots and not self.table.hand_in_progress:
                bot = max(self.bots)
                self.remove_bot(bot)
                seat = bot
            if seat is None:
                return
            self.table.sit(seat, p.name)
            p.seat = seat
            self.queue.pop(0)

    def leave(self, token: str) -> None:
        p = self.players.get(token)
        if p is None:
            return
        if token in self.queue:
            self.queue.remove(token)
        t = self.table
        if p.seat is not None and t.hand_in_progress and p.seat in t.hand.pk_of:
            p.left = True                    # folded out by the timer, removed after the hand
        else:
            if p.seat is not None:
                t.stand(p.seat)
            del self.players[token]
        self._fix_host()

    def _fix_host(self) -> None:
        cands = [p for p in self.players.values() if not p.left]
        if self.host in self.players and not self.players[self.host].left:
            return
        online = [p for p in cands if p.online] or cands
        self.host = online[0].token if online else None

    @property
    def empty(self) -> bool:
        return not any(not p.left for p in self.players.values())

    # ------------------------------------------------------------ dealer's choice
    def chooser_seat(self) -> int | None:
        """Who picks the next game: the next dealer if that's a connected
        player, else the host, else any connected player."""
        t = self.table
        humans = {s: p for s, p in self.humans().items() if not p.left}
        funded = t.funded_seats()
        if t.button is not None and funded:
            nxt = t._next_funded(t.button, funded)
            if nxt in humans and humans[nxt].online:
                return nxt
        hp = self.players.get(self.host)
        if hp and hp.seat is not None and hp.online and not hp.left:
            return hp.seat
        for s in sorted(humans):
            if humans[s].online:
                return s
        return None

    def _override_in(self, p: Player) -> float | None:
        """Seconds until the host may pick for a slow dealer (None: not applicable)."""
        if p.token != self.host or self.table.hand_in_progress:
            return None
        ch = self.chooser_seat()
        if ch is None or ch == p.seat:
            return None
        return max(0.0, self.dealer_wait - (time.monotonic() - self._choose_since))

    def may_deal(self, p: Player) -> bool:
        if p.seat is None:
            return False
        if p.seat == self.chooser_seat():
            return True
        left = self._override_in(p)
        return left is not None and left <= 0

    # ------------------------------------------------------------ requests
    async def handle(self, p: Player, ws: WebSocket, msg: dict) -> None:
        kind = msg.get("type")
        self.last_active = time.monotonic()
        async with self.lock:
            t = self.table
            try:
                if kind == "hello":
                    pass
                elif kind == "preview":
                    pv = preview_choice(t.settings.with_choice(msg), len(t.funded_seats()))
                    await ws.send_json({"type": "preview", "token": msg.get("token"), **pv})
                    return
                elif kind == "random":
                    sel = random_choice(len(t.funded_seats()))
                    pv = preview_choice(t.settings.with_choice(sel), len(t.funded_seats()))
                    await ws.send_json({"type": "random", "selection": sel, **pv})
                    return
                elif kind == "start_hand":
                    if not self.may_deal(p):
                        ch = self.chooser_seat()
                        who = t.seats[ch].name if ch is not None and t.seats[ch] else "the dealer"
                        raise IllegalAction(f"it's {who}'s turn to choose the game")
                    self.table.change_settings(t.settings.with_choice(msg))
                    self.table.start_hand()
                    self._hurry = False
                    self._not_before = time.monotonic() + self.deal_pause
                elif kind == "hurry":
                    self._hurry = True
                    self._not_before = 0.0
                elif kind == "action":
                    amount = msg.get("amount")
                    t.act(self._seat(p), str(msg.get("action")),
                          int(amount) if amount is not None else None, seq=_int(msg, "seq", -1))
                elif kind == "pass":
                    t.pass_card(self._seat(p), str(msg.get("card", "")), seq=_int(msg, "seq", -1))
                    self._not_before = time.monotonic() + 0.6
                elif kind == "declare":
                    t.declare(self._seat(p), msg.get("declaration"), seq=_int(msg, "seq", -1))
                    self._not_before = time.monotonic() + 0.6
                elif kind in ("hit", "stand", "buy", "market_fold", "bid", "drop"):
                    # Blackjack hit/stand; Wall Street buy/fold; Joker auction bid/drop
                    arg = str(_int(msg, "amount", 0)) if kind == "bid" else str(msg.get("card", ""))
                    t.phase_action(self._seat(p), kind, arg, seq=_int(msg, "seq", -1))
                    self._not_before = time.monotonic() + 0.5
                elif kind == "rebuy":
                    t.rebuy(self._seat(p))
                elif kind == "add_bot":
                    self._host_only(p)
                    self.add_bot(str(msg.get("level", "amateur")))
                elif kind == "remove_bot":
                    self._host_only(p)
                    self.remove_bot(_int(msg, "seat", -1))
                else:
                    raise IllegalAction(f"unknown request {kind!r}")
                self._settle()
            except ERRORS as e:
                await ws.send_json({"type": "error", "message": str(e)})
                await self.send_state(p, ws)
                return
        await self.broadcast()
        self.kick()

    def _seat(self, p: Player) -> int:
        if p.seat is None:
            raise IllegalAction("you'll get a seat when this hand ends")
        return p.seat

    def _host_only(self, p: Player) -> None:
        if p.token != self.host:
            raise IllegalAction("only the host can change the bots")

    def _settle(self) -> None:
        """Housekeeping after every change (call with the lock held)."""
        t = self.table
        if t.hand_in_progress:
            return
        if t.hand_no != self._done_seen:            # a hand just ended
            self._done_seen = t.hand_no
            self._choose_since = time.monotonic()
        for p in [p for p in self.players.values() if p.left]:
            if p.seat is not None:
                t.stand(p.seat)
            del self.players[p.token]
        self._seat_queue()
        self._fix_host()

    # ------------------------------------------------------------ views
    def room_info(self, p: Player) -> dict:
        now = time.monotonic()
        ch = self.chooser_seat()
        humans = self.humans()
        host = self.players.get(self.host)
        return {
            "code": self.code,
            "is_host": p.token == self.host,
            "host_seat": host.seat if host else None,
            "waiting_for_seat": p.seat is None,
            "players": {str(s): {"online": q.online, "left": q.left} for s, q in humans.items()},
            "queue": [self.players[x].name for x in self.queue if x in self.players],
            "chooser": ch,
            "you_choose": self.may_deal(p),
            "override_in": self._override_in(p),
            "timers": {str(k[2]): {"left": round(max(0.0, dl - now), 2), "total": total}
                       for k, (dl, total) in self._deadlines.items()},
        }

    async def send_state(self, p: Player, ws: WebSocket) -> None:
        await ws.send_json({"type": "state", "state": self.table.view(p.seat),
                            "room": self.room_info(p)})

    # Seconds the browser spends showing each moment of an update one at a
    # time (web/app.js PACE); bots wait that long so they don't rush ahead.
    STORY_PAUSE = {"board": 1.7, "dice": 3.2, "discard": 1.2}

    def _pace(self) -> None:
        h = self.table.hand
        if h is None or not self.bot_delay:
            return
        hand_no, seen = self._story_seen
        if hand_no != self.table.hand_no:
            seen = 0
        new = h.history[seen:]
        self._story_seen = (self.table.hand_no, len(h.history))
        boards = sum(1 for x in new if x["kind"] == "board")
        delay = (max(0, boards - 1) * self.STORY_PAUSE["board"]
                 + sum(self.STORY_PAUSE[x["kind"]] for x in new if x["kind"] in ("dice", "discard")))
        if delay and not self._hurry:
            self._not_before = max(self._not_before, time.monotonic() + delay)

    async def broadcast(self) -> None:
        self._pace()
        for p in list(self.players.values()):
            for ws in list(p.sockets):
                try:
                    await self.send_state(p, ws)
                except Exception:
                    p.sockets.discard(ws)

    # ------------------------------------------------------------ bots + timers
    def kick(self) -> None:
        if self.closed:
            return
        if self._bot_task is None or self._bot_task.done():
            self._bot_task = asyncio.create_task(self._run_bots())
        if self.table.hand_in_progress and (self._timer_task is None or self._timer_task.done()):
            self._timer_task = asyncio.create_task(self._run_timers())

    def close(self) -> None:
        self.closed = True
        for task in (self._bot_task, self._timer_task):
            if task and not task.done():
                task.cancel()

    def _think_time(self, kind: str, amount, view: dict) -> float:
        """Seconds a person might take for this decision."""
        me = view["seats"][view["you"]]
        stack = me["stack"] + me["bet"]
        cost = (amount or 0) - me["bet"] if kind in ("bet", "raise") else view["legal"]["call"]
        big = stack and cost >= 0.4 * stack
        lo, hi = ((2.2, 3.8) if big else
                  {"fold": (0.5, 1.1), "check": (0.6, 1.2), "call": (0.9, 1.9)}.get(kind, (1.2, 2.4)))
        return random.uniform(lo, hi) * (self.bot_delay / 0.9)

    async def _run_bots(self) -> None:
        while not self.closed:
            t = self.table
            if not t.hand_in_progress or t.hand.actor_seat not in self.bots:
                self._hurry = False            # a person's turn (or hand over): normal speed
                return
            wait = 0.25 if self._hurry else max(min(self.bot_delay, 0.35),
                                                self._not_before - time.monotonic())
            await asyncio.sleep(wait)
            async with self.lock:
                if not t.hand_in_progress or t.hand.actor_seat not in self.bots:
                    continue
                seat = t.hand.actor_seat
                view = t.view(seat)              # the bot sees only its own view
                variant = t.hand.variant
                self.bots[seat].fast = self._hurry
                started = time.monotonic()
                kind, amount = await asyncio.to_thread(self.bots[seat].decide, view, variant)
            # Human-like pause: quick folds, slower raises, a long think before
            # a big all-in decision. "Skip ahead" cuts it short.
            if not self._hurry and self.bot_delay:
                end = time.monotonic() + self._think_time(kind, amount, view) \
                    - (time.monotonic() - started)
                while time.monotonic() < end and not self._hurry and not self.closed:
                    await asyncio.sleep(0.1)
            async with self.lock:
                if not t.hand_in_progress or t.seq != view["seq"] or t.hand.actor_seat != seat:
                    continue                       # table changed meanwhile: decide again
                board_before = sum(map(len, view["board"].values()))
                try:
                    t.act(seat, kind, amount, seq=view["seq"])
                except IllegalAction:
                    log.exception("bot %s chose an illegal action; folding/checking", seat)
                    t.act(seat, "fold" if view["legal"]["fold"] else "check", seq=view["seq"])
                if (t.hand and sum(map(len, t.hand.board().values())) > board_before
                        and not self._hurry):
                    self._not_before = time.monotonic() + 1.0
                self._settle()
            await self.broadcast()
            self.kick()

    def _waits(self) -> dict[tuple, float]:
        """What the table is waiting for from people right now -> time allowed."""
        t, h = self.table, self.table.hand
        humans = self.humans()

        def allowed(seat, base):
            p = humans.get(seat)
            if p is None:
                return None                    # a bot: the bot loop handles it
            if p.left:
                return 0.0
            return base if p.online else min(base, self.offline_time)

        out = {}
        turn = h.phase_turn
        if turn:                                   # hit/stand or buy: a person's turn
            a = allowed(turn[1], self.turn_time)
            if a is not None:
                out[(turn[0], t.hand_no, turn[1], len(h.history))] = a
        elif h.pass_awaiting:
            for s in h.pass_awaiting:
                a = allowed(s, self.choose_time)
                if a is not None:
                    out[("pass", t.hand_no, s, h.pass_stage)] = a
        elif h.awaiting:
            for s in h.awaiting:
                a = allowed(s, self.choose_time)
                if a is not None:
                    out[("declare", t.hand_no, s)] = a
        elif h.actor_seat is not None:
            a = allowed(h.actor_seat, self.turn_time)
            if a is not None:
                out[("act", t.hand_no, h.actor_seat, len(h.history))] = a
        return out

    async def _run_timers(self) -> None:
        while not self.closed:
            changed = False
            async with self.lock:
                t = self.table
                if not t.hand_in_progress:
                    self._deadlines.clear()
                    self._settle()
                    changed = True
                else:
                    now = time.monotonic()
                    wants = self._waits()
                    for k in [k for k in self._deadlines if k not in wants]:
                        del self._deadlines[k]
                        changed = True
                    for k, allowed in wants.items():
                        if k not in self._deadlines:
                            total = self.turn_time if k[0] in ("act", "hit", "buy") \
                                else self.choose_time
                            self._deadlines[k] = (now + allowed, total)
                            changed = True
                        else:                     # went offline / left: shorten
                            dl, total = self._deadlines[k]
                            if now + allowed < dl:
                                self._deadlines[k] = (now + allowed, total)
                                changed = True
                    for k, (dl, _) in list(self._deadlines.items()):
                        if now >= dl:
                            del self._deadlines[k]
                            p = self.humans().get(k[2])
                            try:
                                t.time_out(k[2], "left the table" if p and p.left else
                                           "is offline" if p and not p.online else
                                           "ran out of time")
                            except IllegalAction:
                                pass
                            self._settle()
                            changed = True
                            break                 # recompute on the next tick
            if changed:
                await self.broadcast()
                self.kick()
            if not self.table.hand_in_progress:
                return
            await asyncio.sleep(0.2)


class RoomManager:
    """All rooms, and which room each token belongs to."""

    def __init__(self, **room_kwargs):
        self.rooms: dict[str, GameRoom] = {}
        self.by_token: dict[str, str] = {}
        self.room_kwargs = room_kwargs

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
            if code not in self.rooms:
                return code

    def room_of(self, token: str | None) -> GameRoom | None:
        code = self.by_token.get(token or "")
        room = self.rooms.get(code or "")
        if room is None or token not in room.players:
            self.by_token.pop(token or "", None)
            return None
        return room

    def cleanup(self) -> None:
        now = time.monotonic()
        for code, room in list(self.rooms.items()):
            nobody = not any(p.online for p in room.players.values())
            if room.empty or (nobody and now - room.last_active > IDLE_CLOSE):
                self._close(code)

    def _close(self, code: str) -> None:
        room = self.rooms.pop(code, None)
        if room:
            room.close()
            for tok in list(room.players):
                self.by_token.pop(tok, None)

    async def leave_current(self, token: str) -> None:
        room = self.room_of(token)
        if room is None:
            return
        async with room.lock:
            p = room.players.get(token)
            socks = set(p.sockets) if p else set()
            room.leave(token)
            if p:
                p.sockets.clear()
            room._settle()
        self.by_token.pop(token, None)
        for ws in socks:
            try:
                await ws.send_json({"type": "lobby"})
            except Exception:
                pass
        if room.empty:
            self._close(room.code)
        else:
            await room.broadcast()
            room.kick()

    async def create(self, token: str, ws: WebSocket, msg: dict) -> GameRoom:
        self.cleanup()
        if len(self.rooms) >= MAX_ROOMS:
            raise IllegalAction("the server is busy — try again later")
        bots = _int(msg, "bots", 3)
        level = str(msg.get("bot_level", "amateur"))
        if not 0 <= bots <= SEATS - 1:
            raise ValueError("choose 0 to 5 bots")
        if level not in (*LEVELS, "mixed"):
            raise ValueError("bot level must be noob, amateur, tycoon or mixed")
        # claim=True: at every showdown players pick their own 5 cards
        s = TableSettings(_int(msg, "starting_stack", 500),
                          _int(msg, "small_blind", 10), _int(msg, "big_blind", 10), claim=True)
        s.validate()
        await self.leave_current(token)
        room = GameRoom(self._new_code(), s, **self.room_kwargs)
        p = room.join(token, msg.get("name", ""))
        mix = ["noob", "amateur", "tycoon"]
        for i in range(bots):
            room.add_bot(mix[i % 3] if level == "mixed" else level)
        self.rooms[room.code] = room
        self.by_token[token] = room.code
        p.sockets.add(ws)
        return room

    async def join(self, token: str, ws: WebSocket, msg: dict) -> GameRoom:
        self.cleanup()
        code = str(msg.get("code", "")).strip().upper()
        room = self.rooms.get(code)
        if room is None:
            raise IllegalAction(f"no table with the code {code or '…'} — check the code with your friend")
        if self.room_of(token) is not room:
            await self.leave_current(token)
        async with room.lock:
            p = room.join(token, msg.get("name", ""))
            p.sockets.add(ws)
            p.offline_since = None
            room._fix_host()
        self.by_token[token] = room.code
        return room

    def attach(self, token: str, ws: WebSocket) -> GameRoom | None:
        room = self.room_of(token)
        if room:
            p = room.players[token]
            p.sockets.add(ws)
            p.offline_since = None
        return room

    async def detach(self, token: str | None, ws: WebSocket) -> None:
        room = self.room_of(token)
        if room is None:
            return
        p = room.players.get(token)
        if p and ws in p.sockets:
            p.sockets.discard(ws)
            if not p.sockets:
                p.offline_since = time.monotonic()
                room.last_active = time.monotonic()
            await room.broadcast()
            room.kick()


class Connection:
    """One browser tab's WebSocket and whose token it speaks for."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.token: str | None = None


async def handle_message(manager: RoomManager, conn: Connection, msg: dict) -> None:
    ws, kind = conn.ws, msg.get("type")
    if kind == "hello":
        tok = msg.get("token")
        known = isinstance(tok, str) and (tok in manager.by_token)
        conn.token = tok if known else secrets.token_urlsafe(18)
        await ws.send_json({"type": "welcome", "token": conn.token})
        room = manager.attach(conn.token, ws)
        if room:
            p = room.players[conn.token]
            await room.send_state(p, ws)
            await room.broadcast()             # others see you're back online
            room.kick()
        else:
            code = str(msg.get("room") or "").strip().upper()
            await ws.send_json({"type": "lobby", "join": code if code in manager.rooms else None,
                                "join_missing": bool(code) and code not in manager.rooms})
        return
    if conn.token is None:
        await ws.send_json({"type": "error", "message": "say hello first"})
        return
    try:
        if kind == "create_room":
            room = await manager.create(conn.token, ws, msg)
            await room.broadcast()
            room.kick()
            return
        if kind == "join_room":
            room = await manager.join(conn.token, ws, msg)
            await room.broadcast()
            room.kick()
            return
        if kind == "leave":
            if manager.room_of(conn.token) is None:
                await ws.send_json({"type": "lobby"})
            else:
                await manager.leave_current(conn.token)    # sends "lobby" to your tabs
            return
    except ERRORS as e:
        await ws.send_json({"type": "error", "message": str(e)})
        return
    room = manager.room_of(conn.token)
    if room is None:
        await ws.send_json({"type": "error", "message": "start or join a table first"})
        await ws.send_json({"type": "lobby"})
        return
    await room.handle(room.players[conn.token], ws, msg)
