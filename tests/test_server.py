"""End-to-end over real WebSockets: rooms, friends, bots, timers, reconnects."""
import json
import os

os.environ["POKER_BOT_DELAY"] = "0"

import anyio  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from engine import evaluate as ev  # noqa: E402
from engine.cards import card_str  # noqa: E402
from server import app as app_module  # noqa: E402
from server.room import RoomManager  # noqa: E402


@pytest.fixture
def client():
    app_module.manager.__init__(bot_delay=0, deal_pause=0)
    # one shared event loop for all connections, like the real server
    with TestClient(app_module.app) as c:
        yield c


def recv(ws, timeout=10):
    async def _r():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()
    return json.loads(ws.portal.call(_r)["text"])


def until(ws, pred, timeout=10):
    """Read messages until a state message matches ``pred``; return it."""
    while True:
        m = recv(ws, timeout)
        if m["type"] == "state" and pred(m):
            return m


def hello(ws, token=None, room=None):
    ws.send_json({"type": "hello", "token": token, "room": room})
    w = recv(ws)
    assert w["type"] == "welcome" and w["token"]
    return w["token"]


def create(ws, **kw):
    ws.send_json({"type": "create_room", "name": "Host", "bots": 2, **kw})
    return until(ws, lambda m: True)


def best_decl(room, seat):
    h = room.table.hand
    best = ev.auto_declaration(h.variant, h.dealt[seat], h.board_cards())
    return {rid: {"hole": [card_str(c) for c in r[1]],
                  "board": [card_str(c) for c in r[2] if not isinstance(c, ev.RowJoker)]}
            for rid, r in best.items() if r}


def play_out(room, players):
    """Every person checks/calls until the hand is over. ``players`` maps
    seat -> websocket. Reads the latest state for whoever must act."""
    t = room.table
    for _ in range(400):
        if not t.hand_in_progress:
            return
        h = t.hand
        acted = False
        for seat, ws in players.items():
            if seat in h.pass_awaiting:
                card = next(c for c in h.dealt[seat] if c not in h.up_cards)
                ws.send_json({"type": "pass", "card": card_str(card), "seq": t.seq})
                acted = True
            elif seat in h.awaiting:
                ws.send_json({"type": "declare", "declaration": best_decl(room, seat), "seq": t.seq})
                acted = True
            elif h.actor_seat == seat:
                L = h.legal_actions(seat)
                ws.send_json({"type": "action", "action": "check" if L.check else "call",
                              "seq": t.seq})
                acted = True
            if acted:
                until(ws, lambda m: True)
                break
        if not acted:                      # a bot is thinking: wait for news
            ws = next(iter(players.values()))
            try:
                recv(ws)
            except TimeoutError:
                raise AssertionError(
                    f"stuck: actor={h.actor_seat} awaiting={h.awaiting} pass={h.pass_awaiting} "
                    f"bots={list(room.bots)} people={list(players)} street={h.street_name} "
                    f"bot_task={room._bot_task}") from None
    raise AssertionError("hand did not finish")


def test_solo_table_with_bots(client):
    with client.websocket_connect("/ws") as ws:
        hello(ws)
        assert recv(ws)["type"] == "lobby"
        m = create(ws, bots=3)
        s, room_info = m["state"], m["room"]
        assert len(room_info["code"]) == 5 and room_info["is_host"] and room_info["you_choose"]
        assert s["settings"]["starting_stack"] == 500
        assert {c["id"] for c in s["catalogue"]} == {
            "classic", "double", "rows", "pyramid", "personal", "poker_patti", "floors",
            "tictactoe", "redriver", "hilo", "courchevel", "ironcross",
            "chowaha", "blackjack", "wallstreet"}
        assert s["settings"]["claim"] is True              # you claim your own hand
        room = app_module.manager.rooms[room_info["code"]]
        ws.send_json({"type": "random"})
        r = recv(ws)
        while r["type"] != "random":
            r = recv(ws)
        assert r["ok"] and r["summary"]
        for k, (variant, opts) in enumerate([("classic", {"rule": "fix2"}), ("pyramid", {}),
                                             ("holdem", {})]):
            ws.send_json({"type": "start_hand", "variant_id": variant, "options": opts})
            until(ws, lambda m: m["state"]["hand_no"] == k + 1)
            assert room.table.hand.variant.id == variant
            play_out(room, {0: ws})
            assert room.table.total_chips() == 2000
            if len(room.table.funded_seats()) < 2:
                break
        # an out-of-date action is refused
        ws.send_json({"type": "action", "action": "check", "seq": -5})
        m = recv(ws)
        while m["type"] != "error":
            m = recv(ws)
        ws.send_json({"type": "start_hand", "variant_id": "nope"})
        m = recv(ws)
        while m["type"] != "error":
            m = recv(ws)
        ws.send_json({"type": "leave"})
        m = recv(ws)
        while m["type"] != "lobby":
            m = recv(ws)
        assert not app_module.manager.rooms             # last person left: room closed


def test_two_friends_and_a_bot_share_a_table(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        ta = hello(a)
        recv(a)
        code = create(a, bots=1, name="Asha")["room"]["code"]
        tb = hello(b, room=code)
        lob = recv(b)
        assert lob["type"] == "lobby" and lob["join"] == code
        b.send_json({"type": "join_room", "code": code.lower(), "name": "Ben"})
        mb = until(b, lambda m: True)
        assert mb["state"]["you"] is not None and not mb["room"]["is_host"]
        names = [x["name"] for x in mb["state"]["seats"] if not x["empty"]]
        assert sorted(names) == ["Ada", "Asha", "Ben"]
        assert ta not in json.dumps(mb)                    # nobody sees another's token
        room = app_module.manager.rooms[code]
        seat_a, seat_b = room.players[ta].seat, room.players[tb].seat
        # only the dealer's chooser may deal: before the first hand that's the host
        b.send_json({"type": "start_hand", "variant_id": "classic"})
        m = recv(b)
        while m["type"] != "error":
            m = recv(b)
        assert "choose" in m["message"]
        a.send_json({"type": "start_hand", "variant_id": "classic"})
        sb = until(b, lambda m: m["state"]["hand_active"])
        # Ben's view: his own cards, never Asha's or the bot's
        mine = sb["state"]["seats"][seat_b]["cards"]
        assert mine and len(mine) == 2
        for x in sb["state"]["seats"]:
            if not x["empty"] and x["index"] != seat_b:
                assert x["cards"] is None
        h = room.table.hand
        seen = [c for x in sb["state"]["seats"] if not x["empty"]
                for c in (x["cards"] or []) + x.get("up_cards", [])]
        for c in h.dealt[seat_a]:
            assert card_str(c) not in seen
        play_out(room, {seat_a: a, seat_b: b})
        assert room.table.total_chips() == 1500
        # next game is chosen by the next dealer (if a person), else the host
        ch = room.chooser_seat()
        nxt = room.table._next_funded(room.table.button, room.table.funded_seats())
        assert ch == (nxt if nxt in (seat_a, seat_b) else seat_a)

        # Ben's connection drops; he comes back with his token -> same seat
    with client.websocket_connect("/ws") as b2:
        hello(b2, token=tb)
        m = until(b2, lambda m: True)
        assert m["state"]["you"] == seat_b
        assert m["state"]["seats"][seat_b]["name"] == "Ben"


def test_timer_folds_a_slow_player(client):
    app_module.manager.__init__(bot_delay=0, deal_pause=0, turn_time=0.4, choose_time=0.4)
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        hello(a); recv(a)
        code = create(a, bots=0, name="Asha")["room"]["code"]
        hello(b); recv(b)
        b.send_json({"type": "join_room", "code": code, "name": "Ben"})
        until(b, lambda m: True)
        room = app_module.manager.rooms[code]
        a.send_json({"type": "start_hand", "variant_id": "classic"})
        until(a, lambda m: m["state"]["hand_active"])
        # nobody acts: the timer checks/folds for each person until the hand ends
        m = until(a, lambda m: m["state"]["result"] is not None, timeout=20)
        assert sum(h["kind"] == "timeout" for h in m["state"]["history"]) >= 2
        assert room.table.total_chips() == 1000


def test_friend_replaces_a_bot_when_full(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        hello(a); recv(a)
        code = create(a, bots=5)["room"]["code"]
        room = app_module.manager.rooms[code]
        assert len(room.bots) == 5
        hello(b); recv(b)
        b.send_json({"type": "join_room", "code": code, "name": "Ben"})
        m = until(b, lambda m: True)
        assert m["state"]["you"] is not None
        assert len(room.bots) == 4
        assert room.table.total_chips() == 6 * 500 - 500 + 500   # bot's chips left with it
        # host can add and remove bots between hands; friends can't
        b.send_json({"type": "remove_bot", "seat": min(room.bots)})
        m = recv(b)
        while m["type"] != "error":
            m = recv(b)
        a.send_json({"type": "remove_bot", "seat": min(room.bots)})
        until(a, lambda m: len(room.bots) == 3)
        a.send_json({"type": "add_bot", "level": "tycoon"})
        until(a, lambda m: len(room.bots) == 4)


def test_leaving_mid_hand_folds_you_and_frees_the_seat(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        hello(a); recv(a)
        code = create(a, bots=1)["room"]["code"]
        tb = hello(b); recv(b)
        b.send_json({"type": "join_room", "code": code, "name": "Ben"})
        until(b, lambda m: True)
        room = app_module.manager.rooms[code]
        seat_b = room.players[tb].seat
        a.send_json({"type": "start_hand", "variant_id": "classic"})
        until(a, lambda m: m["state"]["hand_active"])
        b.send_json({"type": "leave"})
        m = recv(b)
        while m["type"] != "lobby":
            m = recv(b)
        seat_a = room.players[next(iter(room.players))].seat
        play_out(room, {seat_a: a})
        if room.table.seats[seat_b] is not None:        # (the update may already be read)
            until(a, lambda m: m["state"]["seats"][seat_b]["empty"], timeout=10)
        assert room.table.seats[seat_b] is None
        assert tb not in room.players
        # Ben's chips left with him; everything else is conserved
        assert room.table.total_chips() == room.table.chips_added


def test_unknown_room_code_is_refused(client):
    with client.websocket_connect("/ws") as a:
        hello(a, room="ZZZZZ")
        assert recv(a)["join_missing"]
        a.send_json({"type": "join_room", "code": "ZZZZZ", "name": "X"})
        assert "no table" in recv(a)["message"]


def test_room_codes_are_unique_and_readable():
    m = RoomManager()
    codes = {m._new_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(len(c) == 5 and not set(c) & set("01IO") for c in codes)
