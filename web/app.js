// POKRR browser client. It only displays what the server sends and sends
// requests back. All rules, cards and chip counts live on the server.
"use strict";

const $ = (id) => document.getElementById(id);
let ws = null;
let state = null;          // latest view from the server
let prev = null;           // previous view (for animations)
let adding = 0;            // chips the player is pushing in (raise builder)
let addingSeq = -1;
let pick = null;           // showdown declaration in progress
let choice = null;         // dealer's choice draft {variant_id, options}
let modalTimer = null, modalHidden = false, modalForHand = -1;

const DENOMS = [10, 20, 50, 100, 500, 1000];
const SUITS = { s: "♠", h: "♥", d: "♦", c: "♣" };
const RANK_LABEL = { T: "10" };
const RANK_ORDER = "23456789TJQKA";
const GRADS = [
  "linear-gradient(135deg,#bcd7ff,#e7c6ff)", "linear-gradient(135deg,#ffd6a5,#ffadad)",
  "linear-gradient(135deg,#caffbf,#9bf6ff)", "linear-gradient(135deg,#fdffb6,#ffc6ff)",
  "linear-gradient(135deg,#a0c4ff,#bdb2ff)", "linear-gradient(135deg,#ffc8dd,#bde0fe)",
];

const fmt = (n) => Number(n).toLocaleString();
const initials = (n) => n.trim().split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
function esc(t) { return String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

function cardEl(code, size = "", extra = "", key = "") {
  const d = el("div", `card ${size} ${extra}`);
  if (key) d.dataset.key = key;
  if (!code) { d.classList.add("back"); return d; }
  if (code[0] === "X") {                   // a real joker card
    d.classList.add("jokercard");
    d.innerHTML = `<span class="jk">🃏</span><span class="jl">JOKER</span>`;
    d.dataset.code = code;
    return d;
  }
  const r = code[0], s = code[1];
  if (s === "h" || s === "d") d.classList.add("red");
  d.innerHTML = `<span class="r">${RANK_LABEL[r] || r}<small>${SUITS[s]}</small></span><span class="s">${SUITS[s]}</span>`;
  d.dataset.code = code;
  return d;
}
function slotEl(size) { return el("div", `card slot ${size}`); }

// Chips: split an amount into the table's denominations.
function chipsFor(amount, max = 7) {
  const out = []; let left = amount;
  for (const d of [...DENOMS].reverse()) while (left >= d && out.length < max) { out.push(d); left -= d; }
  if (left > 0 && out.length < max) out.push(0);   // odd remainder chip
  return out;
}
function stackEl(amount) {
  const s = el("div", "stack");
  chipsFor(amount).forEach(d => s.appendChild(el("div", "chip " + (d ? "d" + d : "odd"))));
  return s;
}
function sortHand(cards) {
  const count = {}; cards.forEach(c => (count[c[0]] = (count[c[0]] || 0) + 1));
  return [...cards].sort((a, b) => (count[b[0]] - count[a[0]]) || (RANK_ORDER.indexOf(b[0]) - RANK_ORDER.indexOf(a[0])));
}

// ------------------------------------------------------------- connection
// Your secret seat token (made by the server). Kept per tab (sessionStorage)
// and as a fallback for the whole browser (localStorage), so a reload or a
// dropped connection gets your seat back.
let roomInfo = null;          // room details: code, host, timers, who chooses...
function store(key, val) {
  try { if (val == null) { sessionStorage.removeItem(key); localStorage.removeItem(key); }
        else { sessionStorage.setItem(key, val); localStorage.setItem(key, val); } } catch {}
}
function stored(key) {
  try { return sessionStorage.getItem(key) || localStorage.getItem(key); } catch { return null; }
}
const urlRoom = () => (new URLSearchParams(location.search).get("room") || "").toUpperCase();
function setUrlRoom(code) {
  const u = new URL(location.href);
  if (code) u.searchParams.set("room", code); else u.searchParams.delete("room");
  if (u.href !== location.href) history.replaceState(null, "", u.href);
}
const nameOf = (i) => (state && state.seats[i] && state.seats[i].name) || (state && state.names && state.names[i]) || "Someone";

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    $("conn").textContent = "connected"; $("conn").className = "conn ok";
    send({ type: "hello", token: stored("pokrr-token"), room: urlRoom() });
  };
  ws.onclose = () => { $("conn").textContent = "reconnecting…"; $("conn").className = "conn"; setTimeout(connect, 1500); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "welcome") store("pokrr-token", msg.token);
    else if (msg.type === "lobby") showLobby(msg);
    else if (msg.type === "state") paceState(msg);
    else if (msg.type === "error") showError(msg.message);
    else if (msg.type === "preview") {
      if (msg.token === previewKey) { preview = msg; if (state && !state.hand_active && !$("modal").hidden) renderPicker(); }
    } else if (msg.type === "random") {
      choice = { ...choice, ...msg.selection, options: { ...msg.selection.options } };
      previewKey = JSON.stringify(selection()); preview = msg;
      renderPicker();
    }
  };
}
// ------------------------------------------------------------- pacing
// "See what's going on": when one update holds several things at once (an
// all-in run-out dealing flop, turn and river; a throw-away followed by the
// next cards; a dice roll), play them one at a time before showing the rest.
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
const PACE = { street: 1700, discard: 1200, dice: 3200 };
const paceQueue = [];
let pacing = false;
function applyState(msg) {
  prev = state; state = msg.state; roomInfo = msg.room || null;
  if (roomInfo) setUrlRoom(roomInfo.code);
  render();
}
function paceState(msg) { paceQueue.push(msg); if (!pacing) pump(); }
const wait = (ms) => new Promise(r => setTimeout(r, REDUCED.matches ? Math.min(ms, 500) : ms));
async function pump() {
  pacing = true;
  try {
    while (paceQueue.length) {
      const msg = paceQueue.shift();
      // several updates waiting (a slow device, a hidden tab): catch up instead of lagging
      if (paceQueue.length < 2 && !window.PACE_OFF) {
        try { await playStory(state, msg.state); } catch (e) { console.error(e); }
      }
      applyState(msg);
    }
  } finally { pacing = false; }
}
// The in-between moments of one update, played on screen before it is shown.
async function playStory(cur, next) {
  if (!cur || !next || cur.hand_no !== next.hand_no || !next.history || !cur.history) return;
  const fresh = next.history.slice(cur.history.length);
  const storyKinds = new Set(["board", "dice", "discard"]);
  const last = fresh.map(h => storyKinds.has(h.kind)).lastIndexOf(true);
  for (let k = 0; k < fresh.length; k++) {
    const h = fresh[k], at = cur.history.length + k;
    if (h.kind === "discard" && h.seat != null) {
      await showDiscard(h.seat);
    } else if (h.kind === "dice") {
      await showDice(h, next);
    } else if (h.kind === "board" && k < last) {
      // more is coming in this same update: show this street on its own first
      prev = state; state = partialState(cur, next, at); render();
      await wait(PACE.street);
    }
  }
}
// The next state as it looked right after history item ``at``: only the board
// cards dealt so far, no result yet, nothing to click.
function partialState(cur, next, at) {
  const hist = next.history.slice(0, at + 1);
  const dealt = new Set();
  hist.forEach(h => { if (h.kind === "board") (h.cards || []).forEach(c => dealt.add(c)); });
  const diced = hist.some(h => h.kind === "dice");
  const full = {};
  for (const [g, cards] of Object.entries(next.board || {})) full[g] = [...cards];
  // before the die is rolled, the card it replaces is still on the board
  if (!diced) (next.dice || []).forEach(d => { if (d.group && full[d.group]) full[d.group][d.index] = d.old; });
  const board = {};
  for (const [g, cards] of Object.entries(full)) {
    const before = (cur.board || {})[g] || [];
    board[g] = [];
    for (const c of cards) { if (dealt.has(c) || before.includes(c)) board[g].push(c); else break; }
  }
  // stacks before any winnings are paid out
  const won = {};
  if (next.result) next.result.pots.forEach(p => p.winners.forEach(w => { won[w.seat] = (won[w.seat] || 0) + w.amount; }));
  const seats = next.seats.map((x, i) => x.empty ? x : { ...x, stack: x.stack - (won[i] || 0) });
  return { ...next, board, history: hist, seats, result: null, legal: null, actor: null, phase: null,
           pass: null, declare: null, awaiting: [], your_hand: cur.your_hand, nuts: cur.nuts,
           dice: hist.some(h => h.kind === "dice") ? next.dice : [], lessons: [] };
}
async function showDiscard(seat) {
  const own = document.querySelector(`[data-key^="s${seat}-"]`);
  const av = own || document.querySelector(`[data-avatar="${seat}"]`), deck = $("deck");
  if (av && deck) {
    const a = center(av.getBoundingClientRect()), d = center(deck.getBoundingClientRect());
    const c = el("div", "card md back fxcard");
    c.style.left = a.x + "px"; c.style.top = a.y + "px";
    $("fx").appendChild(c);
    c.animate([{ transform: "translate(-50%,-50%) rotate(0deg)", opacity: 1 },
               { transform: `translate(calc(-50% + ${(d.x - a.x) * .6}px), calc(-50% + ${(d.y - a.y) * .6 - 40}px)) rotate(-25deg)`, opacity: 1, offset: .6 },
               { transform: `translate(calc(-50% + ${d.x - a.x}px), calc(-50% + ${d.y - a.y}px)) rotate(-60deg) scale(.6)`, opacity: 0 }],
      { duration: REDUCED.matches ? 300 : 1000, easing: "ease-in-out", fill: "forwards" }).onfinish = () => c.remove();
    sfx("card");
  }
  await wait(PACE.discard);
}
const PIPS = ["", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];
async function showDice(h, next) {
  const roll = (next.dice || []).find(d => d.die === h.die) || {};
  const box = el("div", "dice-fx", `<div class="die">⚀</div><div class="dice-text">Rolling the die…</div>`);
  $("fx").appendChild(box);
  const die = box.querySelector(".die"), txt = box.querySelector(".dice-text");
  const spin = REDUCED.matches ? 0 : 1500;
  const t0 = performance.now();
  sfx("flip");
  await new Promise(res => {
    (function tick() {
      if (performance.now() - t0 >= spin) return res();
      die.textContent = PIPS[1 + Math.floor(Math.random() * 6)];
      die.style.transform = `rotate(${Math.floor(Math.random() * 360)}deg) scale(${(0.9 + Math.random() * 0.3).toFixed(2)})`;
      setTimeout(tick, 90);
    })();
  });
  die.textContent = PIPS[h.die]; die.style.transform = "none"; die.classList.add("landed");
  sfx("chips");
  const target = roll.group ? document.querySelector(`[data-key="b-${roll.group}-${roll.index}"]`) : null;
  if (h.old) {
    txt.innerHTML = `Rolled <b>${h.die}</b>: card ${h.die} (${esc(h.old.replace("T", "10"))}) is replaced`;
    if (target) target.classList.add("dice-target");
  } else txt.innerHTML = `Rolled <b>${h.die}</b>: no change`;
  await wait(PACE.dice - spin);
  box.classList.add("bye"); setTimeout(() => box.remove(), 400);
  if (target) target.classList.remove("dice-target");
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
function showError(text) {
  const e = $("error"); e.textContent = text; e.hidden = false;
  clearTimeout(showError.t); showError.t = setTimeout(() => (e.hidden = true), 4500);
}
function showLobby(msg = {}) {
  state = prev = null; roomInfo = null; reveal = null; modalForHand = -1;
  $("lobby").hidden = false; $("game").hidden = true; $("modal").hidden = true;
  $("leave").hidden = true; $("table-chips").hidden = true; $("info-btn").hidden = true; $("sound-btn").hidden = true;
  $("room-chip").hidden = true;
  closeInfo();
  const saved = stored("pokrr-name"); if (saved) $("your-name").value = saved;
  // opened an invite link -> the "join" card comes first, code filled in
  const code = msg.join || "";
  $("join-code").value = code;
  $("lobby").classList.toggle("inviting", !!code);
  $("join-note").textContent = msg.join_missing ? "That table has closed. Start a new one or ask for a new link." : "";
  if (!code) setUrlRoom(null);
}
function myName() {
  const n = $("your-name").value.trim() || "Player";
  store("pokrr-name", n);
  return n;
}

$("setup").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  choice = null;
  send({ type: "create_room", name: myName(), bots: +f.get("bots"), bot_level: f.get("bot_level"),
         starting_stack: +f.get("starting_stack"), small_blind: +f.get("small_blind"), big_blind: +f.get("big_blind") });
});
$("join").addEventListener("submit", (ev) => {
  ev.preventDefault();
  choice = null;
  send({ type: "join_room", code: $("join-code").value.trim().toUpperCase(), name: myName() });
});
$("leave").onclick = () => {
  const others = state && state.seats.some(x => !x.empty && !x.is_bot && x.index !== state.you);
  const text = others ? "Leave this table? If a hand is on, you fold. Your friends keep playing."
    : "Leave this table? The game ends and you go back to the start screen.";
  if (confirm(text)) send({ type: "leave" });
};
// Invite: share the link (phones) or copy it.
async function invite() {
  if (!roomInfo) return;
  const link = `${location.origin}/play?room=${roomInfo.code}`;
  if (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)) {
    // a localhost link only works on this computer
    toast(`Friends can't open a "localhost" link. Start "POKRR online" and play from the link it shows — table code ${roomInfo.code}`);
    try { await navigator.clipboard.writeText(roomInfo.code); } catch {}
    return;
  }
  const text = `Join my POKRR table (play chips only) — code ${roomInfo.code}`;
  try {
    if (navigator.share && matchMedia("(pointer:coarse)").matches) { await navigator.share({ title: "POKRR", text, url: link }); return; }
  } catch { return; }
  try { await navigator.clipboard.writeText(link); toast(`Link copied: ${link}`); }
  catch { prompt("Copy this link and send it to your friends:", link); }
}
function toast(text) {
  const t = el("div", "toast", esc(text)); $("fx").appendChild(t); setTimeout(() => t.remove(), 3200);
}
$("room-chip").onclick = invite;
// ------------------------------------------------------------- fit to window
// A normal web page: it follows the screen and scrolls when needed (layout is
// all CSS, see style.css). JS only marks wide screens ("desk": 900px+, where
// the table and your moves sit side by side) and shrinks a board that is
// wider than its space (big boards on small phones).
let SCALE = 1;                      // kept for the chip-flying maths (no scaling now)
let raiseOpen = false;              // phones: chip tray shown after tapping Raise…
// Two columns (table | your hand + moves): wide screens, and phones held sideways.
const WIDE = matchMedia("(min-width: 900px), (orientation: landscape) and (min-width: 640px)");
function fitScreen() {
  document.body.classList.toggle("desk", WIDE.matches);
  fitBoard();
}
function fitBoard() {
  const wrap = document.querySelector(".board-wrap");
  if (!wrap || $("game").hidden) return;
  wrap.style.zoom = "";
  const avail = wrap.clientWidth, need = wrap.scrollWidth;
  if (need > avail + 1) wrap.style.zoom = Math.max(0.5, avail / need).toFixed(3);
}
let resizeTimer = null;
addEventListener("resize", () => {
  fitScreen(); fitModal();
  // layout switches (one column / two columns) change some controls: redraw once
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state && !$("game").hidden) render(false); }, 150);
});
addEventListener("orientationchange", () => setTimeout(() => { fitScreen(); fitModal(); }, 200));

// ☰ menu (phones): opens the header tools; any tap elsewhere closes it
$("menu-btn").onclick = (e) => { e.stopPropagation(); document.body.classList.toggle("menu-open"); };
document.addEventListener("click", (e) => {
  if (document.body.classList.contains("menu-open") && !e.target.closest("#tools")) document.body.classList.remove("menu-open");
});
$("tools").addEventListener("click", (e) => { if (e.target.closest("button")) setTimeout(() => document.body.classList.remove("menu-open"), 50); });

// ⚙ Settings: learning hints (saved in this browser)
const PREFS = { myhand: true, nuts: true, second: true };
try { Object.assign(PREFS, JSON.parse(localStorage.getItem("pokrr-prefs") || "{}")); } catch {}
function savePrefs() { try { localStorage.setItem("pokrr-prefs", JSON.stringify(PREFS)); } catch {} }
function openSettings() {
  $("set-myhand").checked = PREFS.myhand; $("set-nuts").checked = PREFS.nuts;
  $("set-second").checked = PREFS.second; $("set-sound").checked = soundOn;
  $("settings-modal").hidden = false;
}
$("settings-btn").onclick = openSettings;
$("settings-close").onclick = () => ($("settings-modal").hidden = true);
$("settings-modal").addEventListener("click", (e) => { if (e.target.id === "settings-modal") $("settings-modal").hidden = true; });
[["set-myhand", "myhand"], ["set-nuts", "nuts"], ["set-second", "second"]].forEach(([id, key]) => {
  $(id).onchange = () => { PREFS[key] = $(id).checked; savePrefs(); if (state) render(false); };
});
$("set-sound").onchange = () => { if ($("set-sound").checked !== soundOn) $("sound-btn").click(); };

// (i) button: game rules + hand history in a dialog
function openInfo() { $("info-modal").hidden = false; const h = $("history"); h.scrollTop = h.scrollHeight; }
function closeInfo() { $("info-modal").hidden = true; }
$("info-btn").onclick = openInfo;
$("info-close").onclick = closeInfo;
$("info-modal").addEventListener("click", (e) => { if (e.target.id === "info-modal") closeInfo(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeInfo(); $("settings-modal").hidden = true; } });

// ------------------------------------------------------------- rendering
// One-by-one showdown: players reveal in turn starting left of the dealer,
// each "claims" their hand, and the winner is announced last.
let reveal = null;            // {hand, order, idx, done}
let hiddenSeats = new Set();  // seats whose showdown cards are still face down

function render(fx = true) {
  const s = state;
  $("lobby").hidden = true; $("game").hidden = false;
  $("leave").hidden = false; $("table-chips").hidden = false; $("info-btn").hidden = false;
  $("sound-btn").hidden = false;
  $("table-chips").innerHTML = `Chips on table <b>${fmt(s.chips_on_table)}</b>`;
  $("room-chip").hidden = !roomInfo;
  if (roomInfo) $("room-chip").innerHTML = document.body.classList.contains("desk")
    ? `Table <b>${esc(roomInfo.code)}</b> · Invite friends` : `🔗 <b>${esc(roomInfo.code)}</b>`;
  const rects = captureRects();

  // a showdown we watched happen live -> reveal it player by player
  if (fx && s.result && s.result.showdown && prev && prev.hand_no === s.hand_no && !prev.result
      && (!reveal || reveal.hand !== s.hand_no)) startReveal(s);
  const revealing = reveal && !reveal.done && reveal.hand === s.hand_no;
  hiddenSeats = revealing ? new Set(reveal.order.filter(x => !reveal.shown.has(x) && x !== s.you)) : new Set();
  // while one part of a split pot is being decided, only that part counts
  const focus = revealing ? reveal.focusRow : undefined;
  const potCounts = (p) => !revealing || (focus && p.row === focus);

  const winners = new Set();
  if (s.result) s.result.pots.filter(potCounts).forEach(p => p.winners.forEach(w => winners.add(w.seat)));
  // Highlight only the cards of the hand that actually won each pot: the row
  // that pot was for (split-pot games), or the winner's best row (best-row
  // games). Never mix cards from different rows.
  const winCards = new Set();
  if (s.result) for (const p of s.result.pots.filter(potCounts)) for (const w of p.winners) {
    const h = s.result.hands[w.seat]; if (!h) continue;
    const row = p.row ? h.rows.find(r => r.row === p.row) : null;
    (row ? row.cards : h.cards).forEach(c => winCards.add(c));
  }

  // side panel
  $("variant-name").textContent = s.variant.name;
  $("rules").innerHTML = s.variant.summary.map(x => `<li>${esc(x)}</li>`).join("");
  $("blinds").textContent = `Blinds ${fmt(s.settings.small_blind)} / ${fmt(s.settings.big_blind)} · buy-in ${fmt(s.settings.starting_stack)}`;

  ensurePick(s);
  lastMoves = lastMovesOf(s);
  renderBoard(s, winCards);
  renderPots(s);
  const n = s.seats.length, me = s.you ?? 0;
  const opp = $("opponents"); opp.innerHTML = "";
  for (let k = s.you == null ? 0 : 1; k < n; k++) {      // waiting for a seat: show everyone
    const i = (me + k) % n, seat = s.seats[i];
    if (!seat.empty) opp.appendChild(playerEl(seat, i, s, winners));
  }
  renderMe(s, winners, winCards);
  renderHistory(s.history);
  renderControls();
  renderDeclare();
  fitBoard();
  scheduleModal();
  if (fx) runEffects(rects);
}

const MONSTERS = new Set(["Royal flush", "Straight flush", "Four of a kind", "Trail", "Pure sequence"]);
function royal() {           // the rarest hand gets the full treatment
  flash(); setTimeout(flash, 450);
  banner("👑 Royal flush 👑", "big gold royal");
  sfx("win");
}
function revealOrder(s) {
  // clockwise starting with the first player left of the dealer button
  const n = s.seats.length, btn = s.button ?? 0, out = [];
  for (let k = 1; k <= n; k++) { const i = (btn + k) % n; if (s.result.hands[i]) out.push(i); }
  return out;
}
// The showdown is a script of steps. Split-pot games (Poker Patti, double
// boards, Elevator...) get one showdown per part of the pot.
const STEP_MS = { banner: 1100, show: 1700, rowwin: 2000 };
function startReveal(s) {
  const order = revealOrder(s);
  const rowsInPots = [];
  s.result.pots.forEach(p => { if (p.row && !rowsInPots.includes(p.row)) rowsInPots.push(p.row); });
  const rows = s.variant.rows.filter(r => rowsInPots.includes(r.id));
  const steps = [];
  if (rows.length > 1) {
    rows.forEach(r => {
      steps.push({ type: "banner", text: `${r.label.replace(/\s*\(.*\)/, "")} showdown` });
      order.forEach(seat => steps.push({ type: "show", seat, row: r.id }));
      steps.push({ type: "rowwin", row: r.id, label: r.label.replace(/\s*\(.*\)/, "") });
    });
  } else {
    steps.push({ type: "banner", text: "Showdown" });
    order.forEach(seat => steps.push({ type: "show", seat }));
  }
  reveal = { hand: s.hand_no, order, steps, i: 0, shown: new Set(), focusRow: null, done: false,
             total: steps.reduce((a, st) => a + STEP_MS[st.type], 0) };
  reveal.idx = 0;
  setTimeout(revealStep, 60);        // start once the current screen update is drawn
}
function revealStep() {
  const s = state;
  if (!reveal || !s || s.hand_no !== reveal.hand) return;
  if (reveal.i >= reveal.steps.length) { setTimeout(finishReveal, 300); return; }
  const st = reveal.steps[reveal.i++];
  if (st.type === "banner") {
    reveal.focusRow = null; render(false);
    banner(st.text, "big"); sfx("flip");
  } else if (st.type === "show") {
    const first = !reveal.shown.has(st.seat);
    reveal.shown.add(st.seat);
    reveal.idx = reveal.order.filter(x => reveal.shown.has(x)).length;
    render(false);
    const tile = st.seat === s.you ? $("me") : document.querySelector(`[data-seat="${st.seat}"]`);
    if (tile) {
      tile.classList.add("spot");
      if (first) tile.querySelectorAll(".card").forEach((c, k) =>
        c.animate([{ transform: "rotateY(90deg) scale(1.1)" }, { transform: "none" }], { duration: 380, delay: k * 60, fill: "backwards" }));
    }
    const hand = s.result.hands[st.seat];
    const row = hand && st.row ? hand.rows.find(r => r.row === st.row) : null;
    const label = row ? row.label : hand ? hand.label : "";
    if (label) {
      const plain = label.replace(" (joker)", "");
      bubble(st.seat, row ? `${row.row_label.replace(/\s*\(.*\)/, "")}: ${label}` : label,
             "claim" + (plain === "Royal flush" ? " monster royal" : MONSTERS.has(plain) ? " monster" : ""));
      if (plain === "Royal flush") royal();
      else if (MONSTERS.has(plain)) flash();
    }
    sfx("flip");
  } else if (st.type === "rowwin") {
    reveal.focusRow = st.row;                     // highlight this part's winning cards
    render(false);
    const won = {};
    s.result.pots.filter(p => p.row === st.row).forEach(p => p.winners.forEach(w => (won[w.seat] = (won[w.seat] || 0) + w.amount)));
    Object.entries(won).forEach(([seat, amt]) => bubble(+seat, `Wins ${st.label} · ${fmt(amt)}`, "win"));
    sfx("chips");
  }
  setTimeout(revealStep, STEP_MS[st.type]);
}
function finishReveal() {
  if (!reveal || !state || state.hand_no !== reveal.hand) return;
  reveal.done = true;
  render(false);
  celebrate(state);
}
// chips fly to the winners, with a headline for the winning hand
function celebrate(s) {
  const potEl = $("pot-main");
  const from = potEl ? center(potEl.getBoundingClientRect()) : center($("deck").getBoundingClientRect());
  const won = {};
  s.result.pots.forEach(pt => pt.winners.forEach(w => (won[w.seat] = (won[w.seat] || 0) + w.amount)));
  Object.entries(won).forEach(([seat, amt], k) => {
    const av = document.querySelector(`[data-avatar="${seat}"]`);
    if (!av) return;
    for (let burst = 0; burst < 3; burst++) flyChips(from, center(av.getBoundingClientRect()), amt, 200 + k * 200 + burst * 140);
    setTimeout(() => bubble(+seat, `Wins ${fmt(amt)}`, "win"), 500 + k * 200);
  });
  const top = Object.entries(won).sort((a, b) => b[1] - a[1])[0];
  // split-pot games already announced each part's winner during the showdown
  if (top && s.result.showdown && !s.result.pots.some(p => p.row)) {
    const h = s.result.hands[top[0]];
    const who = +top[0] === s.you ? "You win" : `${nameOf(top[0])} wins`;
    if (h) banner(`${who} · ${h.label.replace(" (joker)", "")}`, MONSTERS.has(h.label.replace(" (joker)", "")) ? "big gold" : "big");
  }
  sfx(won[s.you] ? "win" : "chips");
}

function renderBoard(s, winCards) {
  const revealing = reveal && !reveal.done && reveal.hand === s.hand_no;
  // highlight once revealed (or for the part of the pot being decided now)
  const showdown = s.result && s.result.showdown && (!revealing || !!reveal.focusRow);
  $("stage").textContent = s.hand_no ? `${s.variant.name}${s.variant.wild_label ? " · 🃏 " + s.variant.wild_label : ""}`
    + ` · hand ${s.hand_no} · ${s.hand_active ? s.stage : "complete"}` : "Waiting to deal";
  const board = $("board"); board.innerHTML = "";
  const groups = s.variant.board_groups;
  const nRows = Math.max(1, ...groups.map(g => g.row + g.row_span));
  const size = nRows === 1 ? "xl" : nRows === 2 ? "lg" : nRows <= 3 ? "md" : "";
  // While you choose showdown cards: light up the row you're working on;
  // in pick-your-own games its community cards can be tapped right here.
  const dRow = s.declare && pick ? s.variant.rows.find(r => r.id === pick.active) : null;
  const canPick = dRow && s.variant.selection === "declare";
  // Dice: which board cards were swapped (tagged with the roll)
  const swapped = {};
  (s.dice || []).forEach(d => { if (d.group) swapped[`${d.group}-${d.index}`] = d.die; });
  const boardMarks = specialMarks(s);
  for (const g of groups) {
    if (g.hidden) continue;                                         // spare dice cards
    if (g.optional && !(s.board[g.id] || []).length) continue;     // Red River: not dealt
    const inRow = dRow && dRow.groups.includes(g.id);
    const special = g.id === "special";
    const wrap = el("div", "group" + (special ? " special" : g.row_span > 1 ? " shared" : "")
      + (dRow && !special ? (inRow ? " row-on" : " row-off") : ""));
    wrap.title = g.label;
    if (special) wrap.appendChild(el("span", "slabel " + s.variant.special.kind,
      s.variant.special.kind === "joker" ? "Joker" : s.variant.special.kind === "poison" ? "Poison" : "Poison · ±1 wild"));
    wrap.style.gridRow = `${g.row + 1} / span ${g.row_span}`;
    wrap.style.gridColumn = `${g.col + 1}`;
    const cards = s.board[g.id] || [];
    for (let i = 0; i < g.size; i++) {
      const c = cards[i];
      if (!c) { wrap.appendChild(slotEl(size)); continue; }
      const picked = canPick && inRow && pick.rows[dRow.id].board.includes(c);
      const mark = showdown ? (winCards.has(c) ? "used" : "dim") : (canPick && inRow ? "pick" + (picked ? " picked" : "") : "");
      const ce = cardEl(c, size, mark, `b-${g.id}-${i}`);
      if (swapped[`${g.id}-${i}`]) { ce.classList.add("diced"); ce.appendChild(el("span", "ctag dice", `🎲${swapped[`${g.id}-${i}`]}`)); }
      else if (!special) tagCard(ce, c, boardMarks);
      if (canPick && inRow) ce.onclick = () => toggleBoardPick(dRow, g.id, c);
      wrap.appendChild(ce);
    }
    // Elevator floors: the floor's free jokers sit next to its cards
    const owner = s.variant.rows.find(r => r.jokers && r.groups[0] === g.id);
    if (owner) for (let k = 0; k < owner.jokers; k++) {
      const jt = el("div", `card ${size} jokertile`, `<span class="jk">🃏</span><span class="jl">JOKER</span>`);
      jt.title = "Free joker: plays as any card for this floor";
      wrap.appendChild(jt);
    }
    board.appendChild(wrap);
  }
  // Wall Street: the market of investment cards, with prices
  if (s.market) {
    const m = el("div", "group market");
    m.appendChild(el("span", "slabel market", "MARKET"));
    s.market.cards.forEach((x) => {
      const can = !!(s.buy && s.buy.can_afford.includes(x.code));
      const ce = cardEl(x.code, "lg", can ? "pick" : "", `m-${x.code}`);
      ce.appendChild(el("span", "ctag price", fmt(x.price)));
      if (can) { ce.title = `Buy for ${fmt(x.price)}`; ce.onclick = () => send({ type: "buy", card: x.code, seq: s.seq }); }
      m.appendChild(ce);
    });
    board.appendChild(m);
  }
}

function toggleBoardPick(row, gid, c) {
  const cur = pick.rows[row.id];
  if (cur.board.includes(c)) cur.board = cur.board.filter(x => x !== c);
  else {
    if (row.one_per_group) cur.board = cur.board.filter(x => !(state.board[gid] || []).includes(x));
    cur.board.push(c);
  }
  redrawPick();
}
function redrawPick() { renderBoard(state, new Set()); renderDeclare(); fitBoard(); }

function renderPots(s) {
  const box = $("pots"); box.innerHTML = "";
  const pots = s.pots.filter(p => p.amount > 0);
  const bets = s.seats.reduce((a, x) => a + (x.bet || 0), 0);
  if (!pots.length) {
    const p = el("div", "pot main"); p.id = "pot-main";
    p.appendChild(stackEl(0));
    p.appendChild(el("div", "", `<div class="num">0</div><div class="lbl">pot</div>`));
    box.appendChild(p);
  }
  pots.forEach((pt, i) => {
    const p = el("div", "pot " + (i ? "side" : "main"));
    if (!i) p.id = "pot-main";
    p.appendChild(stackEl(pt.amount));
    const names = pt.eligible.map(x => s.seats[x]?.name).filter(Boolean).join(", ");
    p.appendChild(el("div", "", `<div class="num">${fmt(pt.amount)}</div><div class="lbl">${i ? "side pot " + i : "main pot"}</div>`
      + (i ? `<div class="who">${esc(names)}</div>` : "")));
    box.appendChild(p);
  });
  if (s.hand_active && bets > 0) box.appendChild(el("div", "inplay", `+ ${fmt(bets)} in current bets`));
  if (s.hand_active) box.appendChild(el("div", "inplay", `Total this hand: <b>${fmt(s.total_pot)}</b>`));
}

// Which of your private cards are wild / poisoned (mirrors the server rule;
// display only - the server decides).
const RANKS_STR = "23456789TJQKA";
// Which cards are wild / poisoned right now: worked out by the server for
// your own cards and the board (special card, wild-card rule, jokers).
function specialMarks(s) {
  return { wild: new Set(s.wild_codes || []), dead: new Set(s.dead_codes || []) };
}
function tagCard(ce, code, marks) {
  if (!code || code[0] === "X") return ce;            // a joker shows its own face
  if (marks.wild.has(code)) ce.appendChild(el("span", "ctag wild", "WILD"));
  else if (marks.dead.has(code)) { ce.classList.add("deadcard"); ce.appendChild(el("span", "ctag dead", "POISON")); }
  return ce;
}
// Each player's last move in the current betting round (stays on screen).
function lastMovesOf(s) {
  const out = {};
  if (!s.hand_active) return out;
  for (const h of s.history) {
    if (h.street !== s.stage || (h.kind !== "action" && h.kind !== "blind")) continue;
    const a = h.action;
    out[h.seat] = {
      cls: h.all_in ? "allin" : a,
      text: h.all_in ? `All-in ${fmt(h.amount)}` : a === "fold" ? "Fold" : a === "check" ? "Check"
        : a === "call" ? `Call ${fmt(h.amount)}` : a === "bet" ? `Bet ${fmt(h.amount)}`
        : a === "raise" ? `Raise ${fmt(h.amount)}` : (h.text.includes("small") ? "Small blind" : "Big blind"),
    };
  }
  return out;
}
let lastMoves = {};

function avatarEl(seat, i, s, size = "") {
  const av = el("div", "avatar " + size, esc(initials(seat.name)));
  av.style.background = GRADS[i % GRADS.length];
  av.dataset.avatar = i;
  if (seat.is_button) av.appendChild(el("span", "dealer", "D"));
  if (seat.status === "all-in") av.appendChild(el("span", "badge allin", "ALL-IN"));
  else if (seat.role && s.hand_active) av.appendChild(el("span", "badge role", seat.role.replace("BTN/", "")));
  return av;
}
// Friends at the table: online / offline / left (from the room details).
function presence(i) { return roomInfo && roomInfo.players[i]; }
// A shrinking bar while the table waits for this person (turn timer).
function timerEl(i) {
  const t = roomInfo && roomInfo.timers[i];
  if (!t || !t.total) return null;
  const bar = el("div", "timer"), fill = el("div", "fill");
  bar.appendChild(fill);
  const frac = Math.max(0, Math.min(1, t.left / t.total));
  fill.style.width = (frac * 100) + "%";
  fill.animate([{ width: (frac * 100) + "%" }, { width: "0%" }], { duration: Math.max(1, t.left * 1000), easing: "linear", fill: "forwards" });
  if (t.left < 10) bar.classList.add("low");
  else setTimeout(() => bar.classList.add("low"), (t.left - 10) * 1000);
  return bar;
}
function noteEl(seat, i, s, isMe) {
  const pr = presence(i);
  const away = pr && pr.left ? "left the table" : pr && !pr.online ? "offline" : "";
  const note = seat.declaring ? "choosing cards" : seat.passing ? "passing a card"
    : s.actor === i ? (isMe ? "your turn" : seat.is_bot ? "thinking…" : away || "their turn")
    : seat.status === "busted" ? "out" : away;
  const lm = lastMoves[i];
  const n = el("div", "pnote");
  if (!note && lm && seat.status !== "folded") n.appendChild(el("span", "lastmove " + lm.cls, esc(lm.text)));
  else n.textContent = note;
  return n;
}
function betEl(seat, i) {
  const bet = el("div", "betspot"); bet.dataset.bet = i;
  if (seat.bet > 0) { bet.appendChild(stackEl(seat.bet)); bet.appendChild(el("span", "amt", fmt(seat.bet))); }
  return bet;
}

// Compact opponent tile: avatar + name/stack on one line, cards and last move below.
function playerEl(seat, i, s, winners) {
  const wrap = el("div", "player tile" + (s.actor === i ? " actor" : "") + (seat.status === "folded" ? " folded" : "")
    + (seat.status === "busted" ? " busted" : "") + (winners.has(i) ? " winner" : ""));
  wrap.dataset.seat = i;
  const top = el("div", "tile-top");
  top.appendChild(avatarEl(seat, i, s));
  top.appendChild(el("div", "tinfo",
    `<div class="pname">${esc(seat.name)}${seat.bot_level ? ` <span class="plevel">${esc(seat.bot_level)}</span>` : ""}</div>`
    + `<div class="pstack">${fmt(seat.stack)}</div>`));
  wrap.appendChild(top);
  const ups = new Set(seat.up_cards || []);
  const priv = el("div", "mini-cards" + (seat.card_count - ups.size > 3 ? " many" : ""));
  const open = el("div", "mini-cards open-cards");
  let list = seat.cards || Array(seat.card_count).fill(null);
  if (hiddenSeats.has(i)) list = list.map(c => (c && ups.has(c) ? c : null));   // not revealed yet
  list.forEach((c, k) => (c && ups.has(c) ? open : priv).appendChild(cardEl(c, "sm", "", `s${i}-${k}`)));
  if (seat.status === "folded" && seat.card_count)
    priv.appendChild(el("div", "folded-stamp", `<span>${seat.out_reason === "bust" ? "BUST" : "FOLDED"}</span>`));
  const cardsRow = el("div", "cards-split");
  cardsRow.appendChild(priv);
  if (ups.size) { open.prepend(el("span", "open-tag", "OPEN")); cardsRow.appendChild(open); }
  wrap.appendChild(cardsRow);
  wrap.appendChild(noteEl(seat, i, s, false));
  const tm = timerEl(i); if (tm) wrap.appendChild(tm);
  wrap.appendChild(betEl(seat, i));
  const pr = presence(i);
  if (pr && !pr.online) wrap.classList.add("offline");
  // host: remove a bot between hands
  if (seat.is_bot && roomInfo && roomInfo.is_host && !s.hand_active) {
    const x = el("button", "kick", "✕"); x.title = `Remove ${seat.name}`;
    x.onclick = (e) => { e.stopPropagation(); send({ type: "remove_bot", seat: i }); };
    wrap.appendChild(x);
  }
  return wrap;
}

let hintsOpen = null;              // null = default for the screen size
// Your hand, in the right-hand panel above your moves.
function renderMe(s, winners, winCards) {
  const box = $("me"); box.innerHTML = "";
  const i = s.you, seat = s.seats[i];
  if (seat == null || seat.empty) {
    box.className = "sheet me-panel";
    box.innerHTML = `<div class="hint">The table is full right now — you'll get a seat as soon as this hand ends.</div>`;
    return;
  }
  box.className = "sheet me-panel" + (s.actor === i ? " actor" : "") + (winners.has(i) ? " winner" : "");
  const head = el("div", "me-head");
  head.appendChild(avatarEl(seat, i, s, "small"));
  head.appendChild(el("div", "tinfo", `<div class="label" style="margin:0">Your hand</div>`
    + `<div class="stack-big">${fmt(seat.stack)} <span class="muted">chips</span></div>`));
  head.appendChild(betEl(seat, i));
  box.appendChild(head);
  const n = seat.cards ? seat.cards.length : 0;
  // card sizes grow with the screen in CSS; fewer cards = a bigger size
  const size = n <= 2 ? "xl" : n <= 4 ? "lg" : "md";
  const ups = new Set(seat.up_cards || []);
  const cards = el("div", "cards" + (n - ups.size > 3 ? " many" : ""));
  const open = el("div", "cards open-cards");
  const marks = specialMarks(s);
  if (seat.cards) seat.cards.forEach((c, k) => (ups.has(c) ? open : cards).appendChild(tagCard(cardEl(c, size,
    s.result && s.result.showdown && winners.has(i) && winCards.has(c) ? "used" : "", `s${i}-${k}`), c, marks)));
  else if (seat.status !== "busted") cards.appendChild(slotEl("lg"));
  if (seat.status === "folded" && n) cards.appendChild(el("div", "folded-stamp", "<span>FOLDED</span>"));
  const row = el("div", "cards-split mine");
  row.appendChild(cards);
  if (ups.size) { open.prepend(el("span", "open-tag", "OPEN")); row.appendChild(open); }
  box.appendChild(row);
  box.appendChild(noteEl(seat, i, s, true));
  const tm = timerEl(i); if (tm) box.appendChild(tm);
  if (PREFS.myhand && s.your_hand && s.your_hand.length && s.hand_active) {
    box.appendChild(el("div", "yourhand", `<span class="muted">You have</span>` +
      s.your_hand.map(h => `<b>${s.your_hand.length > 1 || (s.variant.scoring === "best" && s.variant.rows.length > 1)
        ? esc(h.row.replace(/\s*\(.*\)/, "")) + ": " : ""}${esc(h.label)}</b>`).join("")));
  }
  // learning hints: best / second-best possible hands on this board
  const hints = (s.nuts || []).filter(x => (x.kind === "nuts" && PREFS.nuts) || (x.kind === "second" && PREFS.second));
  if (hints.length && s.hand_active) {
    // folded away behind a tap on phones; open by default on bigger screens
    const open = hintsOpen ?? !COMPACT.matches;   // folded away on phones
    const tog = el("button", "hint-toggle", open ? "💡 Hide best possible hands" : "💡 Best possible hands");
    tog.onclick = () => { hintsOpen = !open; renderMe(state, new Set(), new Set()); fitBoard(); };
    box.appendChild(tog);
    if (!open) return;
    const hb = el("div", "hints");
    hints.forEach(x => {
      const line = el("div", x.kind, `${x.kind === "nuts" ? "Nuts" : "2nd best"}${x.row ? ` (${esc(x.row)})` : ""}: <b>${esc(x.label)}</b>`);
      const mini = el("span", "mini");
      x.cards.forEach(c => mini.appendChild(cardEl(c)));
      line.appendChild(mini);
      hb.appendChild(line);
    });
    box.appendChild(hb);
  }
}

function renderHistory(items) {
  const ol = $("history"); ol.innerHTML = "";
  let street = null;
  for (const h of items) {
    if (h.kind !== "board" && h.kind !== "result" && h.street !== street) {
      street = h.street; ol.insertAdjacentHTML("beforeend", `<li class="street">${esc(h.street)}</li>`);
    }
    if (h.kind === "board") street = h.street;
    ol.insertAdjacentHTML("beforeend", `<li class="h-${h.kind}">${esc(h.text)}</li>`);
  }
  ol.scrollTop = ol.scrollHeight;
}

// ------------------------------------------------------------- betting with chips
function renderControls() {
  const c = $("controls"); const s = state; const L = s.legal;
  c.innerHTML = "";
  if (!s.hand_active) {
    const mine = !roomInfo || roomInfo.you_choose;
    const ch = roomInfo ? roomInfo.chooser : null;
    c.innerHTML = `<div class="hint">${mine ? (s.hand_no ? "Hand over — your turn to choose the next game." : "Choose a game to start.")
      : `Waiting for <b>${esc(ch != null ? nameOf(ch) : "the dealer")}</b> to choose the next game…`}</div>`;
    const b = el("button", "primary big", mine ? "Dealer's choice" : "Table & results");
    b.onclick = () => { modalHidden = false; renderModal(); };
    c.appendChild(b);
    return;
  }
  if (s.you == null) { c.innerHTML = `<div class="hint">Watching — you'll be dealt in next hand.</div>`; return; }
  if (s.declare) { c.innerHTML = `<div class="hint">Showdown: claim your hand in the Showdown panel.</div>`; return; }
  if (s.hit) {                       // Blackjack Hold'em: hit or stand
    c.innerHTML = `<div class="hint"><b>Blackjack:</b> your cards total <b class="bjtotal">${s.hit.total}</b>. `
      + `Take another card (over 21 = bust, you're out) or stand?</div>`;
    const row = el("div", "row");
    const hb = el("button", "big primary", "Hit"); hb.onclick = () => { hb.disabled = true; send({ type: "hit", seq: s.seq }); };
    const sb = el("button", "big", "Stand"); sb.onclick = () => { sb.disabled = true; send({ type: "stand", seq: s.seq }); };
    row.appendChild(hb); row.appendChild(sb); c.appendChild(row);
    return;
  }
  if (s.buy) {                       // Wall Street: buy a card or fold
    const mine = s.seats[s.you].bought || 0;
    c.innerHTML = `<div class="hint"><b>Your turn to invest</b> (card ${mine + 1} of ${s.market.buys}): tap a card in the `
      + `market to buy it — its price goes into the pot.</div>`;
    const fb = el("button", "big", "Fold"); fb.onclick = () => { if (confirm("Fold and leave this hand?")) send({ type: "market_fold", seq: s.seq }); };
    c.appendChild(fb);
    return;
  }
  if (s.auction && s.auction.max != null) {   // Joker auction: your turn to bid
    const a = s.auction;
    const lead = a.leader == null ? "No bids yet." : `Top bid: <b>${fmt(a.bid)}</b> by ${esc(a.leader === s.you ? "you" : nameOf(a.leader))}.`;
    c.innerHTML = `<div class="hint"><b>🃏 Joker auction:</b> ${lead} The winner pays into the pot and gets a WILD joker card.</div>`;
    let bid = a.min;
    const row = el("div", "row");
    const minus = el("button", "big", "−"), plus = el("button", "big", "+");
    const go = el("button", "big primary");
    const upd = () => { go.textContent = `Bid ${fmt(bid)}`; minus.disabled = bid <= a.min; plus.disabled = bid + s.settings.big_blind > a.max; };
    minus.onclick = () => { bid = Math.max(a.min, bid - s.settings.big_blind); upd(); };
    plus.onclick = () => { bid = Math.min(a.max, bid + s.settings.big_blind); upd(); };
    go.onclick = () => { go.disabled = true; send({ type: "bid", amount: bid, seq: s.seq }); };
    const drop = el("button", "big", "Drop out");
    drop.onclick = () => { drop.disabled = true; send({ type: "drop", seq: s.seq }); };
    row.appendChild(minus); row.appendChild(go); row.appendChild(plus);
    c.appendChild(row); c.appendChild(drop); upd();
    return;
  }
  if (s.phase) {                     // someone else is hitting / buying / bidding
    const who = nameOf(s.phase.seat);
    const what = { hit: "hit or stand", buy: "buy from the market", bid: "bid for the joker" }[s.phase.kind];
    c.innerHTML = `<div class="hint">Waiting for ${esc(who)} to ${what}…`
      + (s.auction && s.auction.leader != null ? ` Top bid ${fmt(s.auction.bid)} (${esc(nameOf(s.auction.leader))}).` : "") + `</div>`;
    return;
  }
  if (s.pass && s.discard) {         // Pineapple: throw away face-down card(s)
    const left = s.discard.count - s.discard.chosen.length;
    c.innerHTML = `<div class="hint"><b>🍍 Pineapple:</b> tap ${left} card${left > 1 ? "s" : ""} to throw away (face down, gone for good).</div>`;
    const row = el("div", "passcards");
    s.pass.cards.filter(code => !s.discard.chosen.includes(code)).forEach(code => {
      const ce = tagCard(cardEl(code, "md", "pick"), code, specialMarks(s));
      ce.onclick = () => { ce.onclick = null; ce.classList.add("picked"); send({ type: "pass", card: code, seq: s.seq }); };
      row.appendChild(ce);
    });
    c.appendChild(row);
    return;
  }
  if (s.pass) {
    // Anaconda: pass one face-down card to the next player on your left.
    const order = s.seats.filter(x => !x.empty && (x.status === "in" || x.status === "all-in")).map(x => x.index);
    const k = order.indexOf(s.you);
    const to = s.seats[order[(k + 1) % order.length]];
    c.innerHTML = `<div class="hint"><b>Anaconda:</b> tap a card to pass it to <b>${esc(to ? to.name : "the left")}</b>.</div>`;
    const row = el("div", "passcards");
    s.pass.cards.forEach(code => {
      const ce = tagCard(cardEl(code, "md", "pick"), code, specialMarks(s));
      ce.onclick = () => { send({ type: "pass", card: code, seq: s.seq }); row.querySelectorAll(".card").forEach(x => (x.onclick = null)); };
      row.appendChild(ce);
    });
    c.appendChild(row);
    return;
  }
  if (s.pass_awaiting && s.pass_awaiting.length) {
    c.innerHTML = `<div class="hint">Waiting for ${esc(s.pass_awaiting.map(nameOf).join(", "))} to `
      + `${s.variant.pass_mode === "discard" ? "throw away" : "pass"} a card…</div>`;
    return;
  }
  if (!L) {
    const actor = s.seats[s.actor];
    const waitingFor = s.awaiting.length ? s.awaiting.map(nameOf).join(", ") + " to choose cards" : (actor ? actor.name : "…");
    c.innerHTML = `<div class="row hint">Waiting for ${esc(waitingFor)}</div>`;
    if (actor && actor.is_bot) {
      // Skip ahead: bots play instantly until it's your turn again.
      const ff = el("button", "big ff", "⏩ Skip ahead");
      ff.title = "Let the bots play quickly until it's your turn";
      ff.onclick = () => { send({ type: "hurry" }); ff.disabled = true; ff.textContent = "⏩ Skipping…"; };
      c.appendChild(ff);
    }
    return;
  }
  if (addingSeq !== s.seq) { adding = 0; addingSeq = s.seq; raiseOpen = false; }
  const me = s.seats[s.you];
  const act = (action, amount) => send({ type: "action", action, amount, seq: s.seq });
  const row = el("div", "row");
  const btn = (label, fn, cls = "big") => { const b = el("button", cls, esc(label)); b.onclick = fn; row.appendChild(b); return b; };
  if (L.fold) btn("Fold", () => act("fold"));
  if (L.check) btn("Check", () => act("check"));
  if (L.call > 0) btn(`Call ${fmt(L.call)}${L.call >= me.stack ? " · all-in" : ""}`, () => act("call"));
  c.appendChild(row);
  if (!L.raise_kind) return;
  // Phones (one column): the chip tray opens only when you want to raise,
  // so the bar at the bottom stays small.
  if ((!WIDE.matches || innerHeight < 600) && !raiseOpen) {
    const open = el("button", "big", L.raise_kind === "bet" ? "Bet…" : "Raise…");
    open.onclick = () => { raiseOpen = true; renderControls(); };
    row.appendChild(open);
    return;
  }
  const raiseBtn = el("button", "big primary");
  raiseBtn.onclick = () => act(L.raise_kind, me.bet + adding);

  const verb = L.raise_kind === "bet" ? "Bet" : "Raise to";
  const room = L.max_to - me.bet;            // most chips you can add
  const tray = el("div", "tray");
  const info = el("div", "adding");
  const update = () => {
    const to = me.bet + adding;
    const allin = to >= L.max_to;
    info.innerHTML = `chips in<b>+${fmt(adding)}</b>`;
    if (adding === 0) { raiseBtn.textContent = L.raise_kind === "bet" ? "Bet" : "Raise"; raiseBtn.disabled = true; }
    else if (to < L.min_to && !allin) { raiseBtn.textContent = `${verb} ${fmt(to)} (min ${fmt(L.min_to)})`; raiseBtn.disabled = true; }
    else { raiseBtn.textContent = `${verb} ${fmt(to)}${allin ? " · all-in" : ""}`; raiseBtn.disabled = false; }
    tray.querySelectorAll("button.chip").forEach(b => (b.disabled = adding + (+b.dataset.d) > room));
  };
  DENOMS.forEach(d => {
    const b = el("button", `chip d${d}`, d >= 1000 ? "1K" : String(d));
    b.dataset.d = d; b.title = `Add ${d}`;
    b.onclick = () => { adding = Math.min(room, adding + d); update(); };
    tray.appendChild(b);
  });
  tray.appendChild(info);
  const tb = el("div", "tray-btns");
  const clear = el("button", "ghost", "Clear"); clear.onclick = () => { adding = 0; update(); };
  const allin = el("button", "ghost", "All-in"); allin.onclick = () => { adding = room; update(); };
  tb.appendChild(clear); tb.appendChild(allin); tray.appendChild(tb);
  c.appendChild(tray);
  c.appendChild(raiseBtn);
  c.appendChild(el("div", "hint", `Tap chips to build your ${L.raise_kind}. Minimum ${verb.toLowerCase()} ${fmt(L.min_to)}.`));
  update();
}

// ------------------------------------------------------------- showdown choices
// Rows you claim yourself (Blackjack Hold'em's "21" half is counted automatically).
const claimRows = (v) => v.rows.filter(r => r.kind !== "bj21");
function ensurePick(s) {
  if (!s.declare) { pick = null; return; }
  if (!pick || pick.hand !== s.hand_no) {
    pick = { hand: s.hand_no, active: claimRows(s.variant)[0].id, rows: {} };
    claimRows(s.variant).forEach(r => (pick.rows[r.id] = { hole: [], board: [] }));
    // compact screens: bring the board (and the claim panel under it) into view
    if (COMPACT.matches) setTimeout(() => document.querySelector(".middle")?.scrollIntoView({ behavior: "smooth", block: "start" }), 400);
  }
}

// Free jokers a row adds next to `n` of your cards (Elevator floors).
const jokersFor = (r, n) => Math.max(0, Math.min(r.jokers || 0, 5 - n));
// Best-row games with several rows: you claim ONE row.
const oneRow = (v) => v.selection === "declare" && v.scoring === "best" && v.rows.length > 1;

// What a row still needs, in plain words ("" when the row is complete).
function rowNeeds(v, r) {
  const p = pick.rows[r.id];
  if (v.selection !== "declare") {                       // split: just give cards
    const left = r.hole_alloc - p.hole.length;
    return left > 0 ? `tap ${left} more of your cards` : "";
  }
  if (r.kind === "teen_patti") {
    const left = 3 - p.hole.length;
    return left > 0 ? `tap ${left} more of your cards` : left < 0 ? `${-left} card${left < -1 ? "s" : ""} too many` : "";
  }
  const need = [];
  const jk = jokersFor(r, p.hole.length);
  const total = p.hole.length + p.board.length + jk;
  const allowed = r.hole_use;
  if (!allowed.includes(p.hole.length)) {
    need.push(allowed.length === 1 ? `use exactly ${allowed[0]} of your cards (now ${p.hole.length})`
      : `use ${allowed[0]}–${allowed[allowed.length - 1]} of your cards`);
  }
  if (total < 5) need.push(`${5 - total} more card${5 - total > 1 ? "s" : ""} to reach 5`);
  if (total > 5) need.push(`${total - 5} card${total - 5 > 1 ? "s" : ""} too many`);
  return need.join(" · ");
}

function renderDeclare() {
  const box = $("declare"); const s = state;
  document.body.classList.toggle("declaring", !!(s.declare && pick));
  if (!s.declare || !pick) { box.hidden = true; return; }
  box.hidden = false;
  const v = s.variant, hole = s.declare.hole;
  const split = v.split_hole_cards, chooseAll = v.selection === "declare";
  const row = v.rows.find(r => r.id === pick.active);
  const cur = pick.rows[row.id];
  const single = oneRow(v);
  // A row left completely empty gives up that part (asked to confirm).
  const empty = (r) => chooseAll && !pick.rows[r.id].hole.length && !pick.rows[r.id].board.length;
  const allDone = single ? !rowNeeds(v, row)
    : claimRows(v).every(r => !rowNeeds(v, r) || empty(r)) && claimRows(v).some(r => !rowNeeds(v, r));

  box.innerHTML = "";
  const head = el("div", "dhead");
  head.appendChild(el("h3", "", single ? "Showdown — claim your hand (pick one row)" : "Showdown — claim your hand"));
  if (claimRows(v).length > 1) {
    const tabs = el("div", "tabs");
    claimRows(v).forEach(r => {
      const ok = !single && !rowNeeds(v, r);
      const b = el("button", "seg" + (pick.active === r.id ? " on" : "") + (ok ? " done" : ""),
        `${esc(r.label)}${ok ? " ✓" : ""}`);
      b.onclick = () => { pick.active = r.id; redrawPick(); };
      tabs.appendChild(b);
    });
    head.appendChild(tabs);
  }
  box.appendChild(head);

  // Step-by-step instruction for the selected row.
  const howMany = split ? row.hole_alloc : null;
  let how;
  if (!chooseAll) how = `<b>${esc(row.label)}:</b> tap ${howMany} of your cards below to give them to this row. `
    + `The row's community cards are lit up on the table — the best hand is made for you.`;
  else if (row.kind === "teen_patti") how = `<b>${esc(row.label)}:</b> tap 3 of your cards — they play Teen Patti on their own. A weaker pick counts!`;
  else how = `<b>${esc(row.label)}:</b> tap your cards below and the lit-up community cards on the table `
    + `to make 5 cards. Rule: ${row.hole_use.length === 1 ? `exactly ${row.hole_use[0]}` : row.hole_use.join(", ")} of your cards`
    + (row.one_per_group ? ", at most one card from each pyramid row" : "")
    + (row.jokers ? `. This row's ${row.jokers} free joker${row.jokers > 1 ? "s" : ""} fill${row.jokers > 1 ? "" : "s"} in automatically` : "")
    + ". A weaker pick counts!"
    + (single ? " You claim ONE row — use the buttons above to pick which." : "");
  box.appendChild(el("div", "how", how));

  const hc = el("div", "cards");
  hole.forEach(c => {
    const owner = Object.entries(pick.rows).find(([, p]) => p.hole.includes(c));
    const ce = tagCard(cardEl(c, "md", "pick" + (cur.hole.includes(c) ? " picked" : "")), c, specialMarks(s));
    if (split && owner) ce.appendChild(el("span", "tagrow" + (owner[0] === row.id ? " here" : ""),
      esc(v.rows.find(r => r.id === owner[0]).label)));
    ce.onclick = () => {
      if (cur.hole.includes(c)) cur.hole = cur.hole.filter(x => x !== c);
      else {
        if (split) Object.values(pick.rows).forEach(p => (p.hole = p.hole.filter(x => x !== c)));
        if (split && !chooseAll && cur.hole.length >= row.hole_alloc) cur.hole.shift();   // keep the row at its size
        cur.hole.push(c);
        // row complete -> move on to the next unfinished row
        if (!single && !rowNeeds(v, row)) {
          const next = claimRows(v).find(r => rowNeeds(v, r));
          if (next) pick.active = next.id;
        }
      }
      redrawPick();
    };
    hc.appendChild(ce);
  });
  box.appendChild(hc);

  const need = rowNeeds(v, row);
  let status = need ? `${esc(row.label)}: ${need}` : `${esc(row.label)} is ready ✓`;
  if (chooseAll && row.kind !== "teen_patti") {
    const jk = jokersFor(row, cur.hole.length);
    status += ` — chosen ${cur.hole.length} of yours + ${cur.board.length} community` + (jk ? ` + ${jk} free joker${jk > 1 ? "s" : ""} 🃏` : "");
  }
  box.appendChild(el("div", "status" + (need ? "" : " ok"), status));

  const go = el("div", "go");
  const submit = el("button", "primary big", single ? `Claim ${row.label.replace(/\s*\(.*\)/, "")}` : "Lock in my cards");
  submit.disabled = !allDone;
  submit.onclick = () => {
    const skipped = single ? [] : claimRows(v).filter(r => empty(r)).map(r => r.label.replace(/\s*\(.*\)/, ""));
    if (skipped.length && !confirm(`You haven't claimed ${skipped.join(", ")}. Give up that part of the pot?`)) return;
    send({ type: "declare", seq: s.seq, declaration: single ? { [row.id]: pick.rows[row.id] } : pick.rows });
  };
  go.appendChild(submit);
  if (!allDone && !single) {
    const waiting = claimRows(v).filter(r => rowNeeds(v, r)).map(r => r.label).join(", ");
    go.appendChild(el("span", "muted", `Still to finish: ${esc(waiting)}`));
  }
  const clear = el("button", "ghost", "Start over");
  clear.onclick = () => { claimRows(v).forEach(r => (pick.rows[r.id] = { hole: [], board: [] })); pick.active = claimRows(v)[0].id; redrawPick(); };
  go.appendChild(clear);
  box.appendChild(go);
}

// ------------------------------------------------------------- between hands
function scheduleModal() {
  const s = state;
  if (s.hand_active) { $("modal").hidden = true; clearTimeout(modalTimer); modalTimer = null; return; }
  if (modalForHand !== s.hand_no) {           // a hand just ended (or first deal)
    modalForHand = s.hand_no; modalHidden = false; pickerTab = "game"; modalPage = "result";
    clearTimeout(modalTimer);
    const staged = reveal && reveal.hand === s.hand_no;      // one-by-one showdown running
    const delay = !s.result ? 0 : staged ? reveal.total + 300 + 2800
      : s.result.showdown ? 3200 : 1800;
    $("modal").hidden = true;
    modalTimer = setTimeout(() => { modalTimer = null; renderModal(); }, delay);
    return;
  }
  if (!modalTimer) renderModal();
}

let modalPage = "result";        // phones: "result" first, then "picker"
function renderModal() {
  const s = state; if (!s || s.hand_active) return;
  $("modal").hidden = modalHidden;
  if (modalHidden) return;
  // On phones the results and the game picker are two steps, not side by side.
  const small = !document.body.classList.contains("desk");
  const stepResult = small && s.result && modalPage === "result";
  const stepPicker = small && s.result && modalPage === "picker";
  renderResultBox();
  $("result").hidden = !s.result || stepPicker;
  $("modal").querySelector(".modal-card").classList.toggle("split", !!s.result && !small);
  if (stepResult) {
    const box = $("picker"); box.innerHTML = "";
    const row = el("div", "dealrow");
    const mine = !roomInfo || roomInfo.you_choose;
    const next = el("button", "primary big", mine ? "Choose the next game ▸" : "Next ▸");
    next.onclick = () => { modalPage = "picker"; renderModal(); };
    const hide = el("button", "ghost", "View table"); hide.onclick = () => { modalHidden = true; renderModal(); };
    row.appendChild(hide); row.appendChild(el("span", "spacer")); row.appendChild(next);
    box.appendChild(row);
    fitModal();
    return;
  }
  renderPicker();
  if (stepPicker) {
    const back = el("button", "ghost", "◂ Results");
    back.onclick = () => { modalPage = "result"; renderModal(); };
    $("picker").prepend(back);
  }
}

// The results + dealer's-choice dialog shrinks itself to fit the screen
// (many players x rows, long rules) so it never needs scrolling.
function fitModal() {
  // dialogs scroll now (no shrinking); just start at the top when opened
  const m = $("modal");
  if (m && !m.hidden && !m.dataset.shown) { m.scrollTop = 0; m.dataset.shown = "1"; }
  if (m && m.hidden) delete m.dataset.shown;
}

function renderResultBox() {
  const s = state, box = $("result");
  box.hidden = !s.result;
  if (!s.result) { box.innerHTML = ""; return; }
  const winners = new Set(); s.result.pots.forEach(p => p.winners.forEach(w => winners.add(w.seat)));
  let html = `<div class="headline">${esc(s.result.summary[0] || "")}</div>`;
  if (s.result.summary.length > 1) html += `<ul>${s.result.summary.slice(1).map(l => `<li>${esc(l)}</li>`).join("")}</ul>`;
  const hands = Object.entries(s.result.hands);
  const played = [];       // per row line: cards as played (jokers replaced)
  if (hands.length) {
    html += `<div class="hands">`;
    for (const [seat, h] of hands) {
      const net = s.result.net[seat];
      html += `<div class="hand ${winners.has(+seat) ? "win" : ""}"><div class="who"><b>${esc(nameOf(seat))}</b>
        <span class="net ${net > 0 ? "up" : ""}">${net >= 0 ? "+" : ""}${fmt(net)}</span></div><div class="rows">`;
      for (const r of h.rows) {
        played.push(r.played || r.cards.map(c => ({ code: c, joker: null })));
        html += `<div class="rowline"><div class="cards" data-played="${played.length - 1}"></div>
          <span>${h.rows.length > 1 ? esc(r.row_label.replace(/\s*\(.*\)/, "")) + ": " : ""}${esc(r.label)}</span></div>`;
        if (r.joker_text) html += `<div class="jokerline">🃏 ${esc(r.joker_text.replace(/T/g, "10"))}</div>`;
      }
      html += `</div></div>`;
    }
    html += `</div>`;
  }
  // Learn from this hand: private notes + where the hands sit on the ladder
  if (s.lessons && s.lessons.length) {
    const ladder = ["High card", "One pair", "Two pair", "Three of a kind", "Straight", "Flush",
                    "Full house", "Four of a kind", "Straight flush", "Royal flush"];
    const mine = s.result.hands[s.you]?.label?.replace(" (joker)", "");
    const top = [...winners].map(w => s.result.hands[w]?.label?.replace(" (joker)", "")).filter(Boolean);
    const rungs = ladder.slice().reverse().map(l =>
      `<span class="rung${top.includes(l) ? " top" : ""}${l === mine ? " mine" : ""}">${esc(l)}</span>`).join("");
    html += `<div class="learn"><div class="label">Learn from this hand</div>
      <ul>${s.lessons.map(x => `<li>${esc(x.replace(/\bT([shdc])\b/g, "10$1"))}</li>`).join("")}</ul>
      ${ladder.includes(mine) || top.some(t => ladder.includes(t)) ? `<div class="ladder">${rungs}</div>` : ""}</div>`;
  }
  box.innerHTML = html;
  box.querySelectorAll("[data-played]").forEach(e => {
    const cards = played[+e.dataset.played].slice()
      .sort((a, b) => RANK_ORDER.indexOf(b.code[0]) - RANK_ORDER.indexOf(a.code[0]));
    cards.forEach(p => {
      const ce = cardEl(p.code, "xs", p.joker ? "jokered" : "");
      if (p.joker) { ce.title = `${p.joker} is a joker, playing as ${p.code}`; ce.appendChild(el("span", "jtag", "🃏")); }
      e.appendChild(ce);
    });
  });
}

// Dealer's choice: a game family + its adjustable parts + add-ons. The rules
// text and "can this be dealt?" come from the server (message "preview").
let preview = null, previewKey = "";
function selection() {
  return { variant_id: choice.variant_id, options: { ...choice.options }, special_kind: choice.special_kind,
           special_stage: choice.special_stage, special_scope: choice.special_scope, anaconda: choice.anaconda,
           pineapple: choice.pineapple || "off", pine_count: choice.pine_count || 1,
           dice: !!choice.dice, bounty: !!choice.bounty,
           wild: choice.wild || "off", auction: !!choice.auction, deck: choice.deck || "standard" };
}
function requestPreview() {
  const key = JSON.stringify(selection());
  if (key === previewKey && preview) return;
  previewKey = key; preview = null;
  send({ type: "preview", token: key, ...selection() });
}
// blocked: {value: reason} from the server: choices that don't fit this game
// (they're greyed out, or left out when hide is set)
function segLine(label, choices, current, onPick, blocked = null, hide = false) {
  const line = el("div", "opt", `<span>${esc(label)}</span>`);
  choices.forEach(([v, lab]) => {
    const why = blocked && blocked[String(v).toLowerCase()];
    if (why && hide && current !== v) return;
    const b = el("button", "seg" + (current === v ? " on" : "") + (why && current !== v ? " blocked" : ""), esc(lab));
    if (why && current !== v) { b.disabled = true; b.title = why; }
    b.onclick = () => { onPick(v); renderPicker(); };
    line.appendChild(b);
  });
  return line;
}

// Who's here + invite + (host) add bots. Shown between hands.
let overrideOK = -1;          // hand number for which the host chose "pick for them"
let pickerTab = "game";       // dealer's choice: game | options | addons | rules
function roomStrip(s) {
  if (!roomInfo) return el("div");
  const strip = el("div", "roomstrip");
  const people = s.seats.filter(x => !x.empty && !x.is_bot).length;
  const bots = s.seats.filter(x => !x.empty && x.is_bot).length;
  strip.appendChild(el("span", "who", `Table <b>${esc(roomInfo.code)}</b> · ${people} ${people === 1 ? "player" : "players"} · ${bots} ${bots === 1 ? "bot" : "bots"}`));
  const inv = el("button", "", "🔗 Invite friends"); inv.onclick = invite; strip.appendChild(inv);
  const free = s.seats.filter(x => x.empty).length;
  if (roomInfo.is_host && free > 0) {
    const lv = el("select");
    [["noob", "Noob"], ["amateur", "Amateur"], ["tycoon", "Tycoon"]].forEach(([v, l]) => {
      const o = el("option", "", l); o.value = v; if (v === (stored("pokrr-botlevel") || "amateur")) o.selected = true; lv.appendChild(o);
    });
    lv.onchange = () => store("pokrr-botlevel", lv.value);
    const add = el("button", "", "+ Add bot");
    add.onclick = () => send({ type: "add_bot", level: lv.value });
    strip.appendChild(lv); strip.appendChild(add);
  }
  if (roomInfo.is_host && bots) strip.appendChild(el("span", "muted", "Tap ✕ on a bot to remove it"));
  if (roomInfo.queue.length) strip.appendChild(el("span", "muted", `Waiting for a seat: ${esc(roomInfo.queue.join(", "))}`));
  return strip;
}

function renderWaitingForDealer(s, box) {
  const ch = roomInfo.chooser;
  box.appendChild(el("h3", "", ch != null ? `${esc(nameOf(ch))} is choosing the ${s.hand_no ? "next" : "first"} game…`
    : "Waiting for a player to come back…"));
  box.appendChild(roomStrip(s));
  box.appendChild(el("div", "muted", "Dealer's choice moves round the table with the dealer button. When the button is with a bot, the host chooses."));
  const dr = el("div", "dealrow");
  const me = s.seats[s.you];
  if (me && me.stack === 0) {
    const rb = el("button", "", `Rebuy ${fmt(s.settings.starting_stack)}`); rb.onclick = () => send({ type: "rebuy" }); dr.appendChild(rb);
  }
  dr.appendChild(el("span", "spacer"));
  const oi = roomInfo.override_in;
  if (oi != null) {
    if (oi <= 0) {
      const o = el("button", "primary big", "Choose for them");
      o.title = "They're taking a while — as host you can pick the game";
      o.onclick = () => { overrideOK = s.hand_no; renderPicker(); };
      dr.appendChild(o);
    } else {
      clearTimeout(renderWaitingForDealer.t);
      renderWaitingForDealer.t = setTimeout(() => { if (roomInfo) { roomInfo.override_in = 0; if (!$("modal").hidden) renderPicker(); } }, oi * 1000 + 300);
    }
  }
  const hide = el("button", "ghost", "View table"); hide.onclick = () => { modalHidden = true; renderModal(); };
  dr.appendChild(hide);
  box.appendChild(dr);
  fitModal();
}

function renderPicker() {
  const s = state, box = $("picker");
  const cat = s.catalogue || [];
  // phones show the results first; the picker is the next step
  if (!document.body.classList.contains("desk") && s.result && modalPage === "result") return;
  if (roomInfo && !roomInfo.you_choose && overrideOK !== s.hand_no) {
    box.innerHTML = "";
    renderWaitingForDealer(s, box);
    return;
  }
  if (!choice) choice = { variant_id: s.settings.variant_id, options: { ...s.settings.variant_options },
                          special_kind: s.settings.special_kind || "none", special_stage: s.settings.special_stage || "River",
                          special_scope: s.settings.special_scope || "private", anaconda: s.settings.anaconda || "off",
                          pineapple: s.settings.pineapple || "off", pine_count: s.settings.pine_count || 1,
                          dice: !!s.settings.dice, bounty: !!s.settings.bounty,
                          wild: s.settings.wild || "off", auction: !!s.settings.auction,
                          deck: s.settings.deck || "standard" };
  let fam = cat.find(p => p.id === choice.variant_id);
  if (!fam) { fam = cat[0]; choice.variant_id = fam.id; choice.options = {}; }
  fam.options.forEach(o => { if (!o.choices.some(c => c.value === choice.options[o.key])) choice.options[o.key] = o.default; });
  requestPreview();

  box.innerHTML = "";
  // Header: what's chosen so far, in plain words
  const p = preview;
  const blk = (p && p.blocks) || {};
  const head = el("div", "pick-head");
  head.appendChild(el("h3", "", s.hand_no ? "Next hand — your choice" : "Dealer's choice — pick the first game"));
  const addons = [];
  if (choice.special_kind !== "none") addons.push({ joker: "🃏 Joker", poison: "☠ Poison", jumping: "🦘 Jumping joker" }[choice.special_kind]);
  if ((choice.wild || "off") !== "off") addons.push("🃏 " + { deuces: "Deuces wild", oneeyed: "One-eyed jacks", jokers: "2 jokers", queen: "Follow the Queen", river: "Wild river" }[choice.wild]);
  if (choice.auction) addons.push("🃏 Joker auction");
  if (choice.anaconda !== "off") addons.push("🐍 Anaconda");
  if ((choice.pineapple || "off") !== "off") addons.push("🍍 Pineapple");
  if (choice.dice) addons.push("🎲 Dice");
  if (choice.bounty) addons.push("7-2 bounty");
  if ((choice.deck || "standard") !== "standard") addons.push(choice.deck === "short" ? "Short deck" : "Royal deck");
  head.appendChild(el("div", "pick-sum", `<b>${esc((p && p.name) || fam.name)}</b>`
    + addons.map(a => `<span class="addon-chip">${esc(a)}</span>`).join("")));
  box.appendChild(head);
  box.appendChild(roomStrip(s));

  // Tabs: one panel at a time (game / its options / add-ons / rules)
  const tabs = el("div", "pick-tabs");
  [["game", "Game"], ["options", "Options"], ["addons", `Add-ons${addons.length ? ` (${addons.length})` : ""}`], ["rules", "Rules"]]
    .forEach(([id, label]) => {
      const b = el("button", "seg" + (pickerTab === id ? " on" : ""), esc(label));
      b.onclick = () => { pickerTab = id; renderPicker(); };
      tabs.appendChild(b);
    });
  box.appendChild(tabs);
  const panel = el("div", "pick-panel");
  if (pickerTab === "game") {
    const list = el("div", "families");
    const rnd = el("button", "preset random", `<b>🎲 Random</b><span>Any game, any options, maybe a joker</span>`);
    rnd.onclick = () => send({ type: "random" });
    list.appendChild(rnd);
    cat.forEach(fp => {
      const b = el("button", "preset" + (fp.id === fam.id ? " on" : ""), `<b>${esc(fp.name)}</b><span>${esc(fp.pitch)}</span>`);
      b.onclick = () => { choice.variant_id = fp.id; choice.options = {}; renderPicker(); };
      list.appendChild(b);
    });
    panel.appendChild(list);
  } else if (pickerTab === "options") {
    const opts = el("div", "opts");
    fam.options.forEach(o => opts.appendChild(segLine(o.label, o.choices.map(c => [c.value, c.label]),
      choice.options[o.key], v => (choice.options[o.key] = v))));
    opts.appendChild(segLine("Deck", [["standard", "Standard 52"], ["short", "Short (6 to A)"], ["royal", "Royal (10 to A)"]],
      choice.deck || "standard", v => (choice.deck = v), blk.deck, true));
    panel.appendChild(opts);
  } else if (pickerTab === "addons") {
    const opts = el("div", "opts");
    opts.appendChild(el("div", "muted", "Greyed-out choices don't fit this game (or what you've already picked); the reasons are at the bottom."));
    opts.appendChild(el("div", "opt-sep", "Wild cards"));
    opts.appendChild(segLine("🃏 Wild rule", [["off", "Off"], ["deuces", "Deuces wild"], ["oneeyed", "One-eyed jacks"],
      ["jokers", "2 jokers in deck"], ["queen", "Follow the Queen"], ["river", "Wild river"]],
      choice.wild || "off", v => (choice.wild = v), blk.wild));
    opts.appendChild(segLine("Special card", [["none", "None"], ["joker", "🃏 Joker"], ["poison", "☠ Poison"], ["jumping", "🦘 Jumping joker"]],
      choice.special_kind, v => (choice.special_kind = v), blk.special_kind));
    if (choice.special_kind !== "none") {
      opts.appendChild(segLine("Turned up with the", [["Flop", "Flop"], ["Turn", "Turn"], ["River", "River"]],
        choice.special_stage, v => (choice.special_stage = v)));
      opts.appendChild(segLine("Affects", [["private", "Private cards only"], ["all", "Private + community"]],
        choice.special_scope, v => (choice.special_scope = v)));
    }
    opts.appendChild(segLine("🃏 Joker auction", [[false, "Off"], [true, "After the flop"]],
      !!choice.auction, v => (choice.auction = v), blk.auction));
    opts.appendChild(el("div", "opt-sep", "Card swaps"));
    opts.appendChild(segLine("🐍 Anaconda (pass left)", [["off", "Off"], ["flop", "After the flop"], ["every", "Every round"]],
      choice.anaconda, v => { choice.anaconda = v; if (v !== "off") choice.pineapple = "off"; }, blk.anaconda));
    opts.appendChild(segLine("🍍 Pineapple (throw away)", [["off", "Off"], ["preflop", "Before the flop"], ["flop", "After the flop"], ["every", "Every round"]],
      choice.pineapple || "off", v => { choice.pineapple = v; if (v !== "off") choice.anaconda = "off"; }, blk.pineapple));
    if ((choice.pineapple || "off") !== "off")
      opts.appendChild(segLine("Cards thrown each time", [[1, "1 card"], [2, "2 cards (Irish)"]],
        choice.pine_count || 1, v => (choice.pine_count = v)));
    opts.appendChild(segLine("🎲 Dice", [[false, "Off"], [true, "Roll after the river"]], !!choice.dice, v => (choice.dice = v), blk.dice));
    opts.appendChild(el("div", "opt-sep", "Side bets"));
    opts.appendChild(segLine("7-2 bounty", [[false, "Off"], [true, "Win with 7-2, everyone pays"]], !!choice.bounty, v => (choice.bounty = v), blk.bounty));
    const why = [...new Set(Object.entries(blk).filter(([k]) => k !== "deck").flatMap(([, m]) => Object.values(m)))];
    if (why.length) opts.appendChild(el("div", "why-not", `<b>Not available here</b><ul>${why.map(w => `<li>${esc(w[0].toUpperCase() + w.slice(1))}</li>`).join("")}</ul>`));
    panel.appendChild(opts);
  } else {
    panel.appendChild(el("div", "rulebox", p
      ? `<b>${esc(p.name || fam.name)} — rules</b><ul>${p.summary.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`
      : `<span class="muted">Checking the rules…</span>`));
  }
  if (p && !p.ok) panel.appendChild(el("div", "cant", `Can't deal this: ${esc(p.reason)}`));
  box.appendChild(panel);
  const combo = { ok: !!(p && p.ok) };
  const resolved = { ...choice.options };
  const preset = fam;
  const me = s.seats[s.you];
  const dr = el("div", "dealrow");
  const sb = el("input"); sb.type = "number"; sb.min = 1; sb.step = 10; sb.value = s.settings.small_blind;
  const bb = el("input"); bb.type = "number"; bb.min = 1; bb.step = 10; bb.value = s.settings.big_blind;
  dr.appendChild(el("span", "muted", "Blinds")); dr.appendChild(sb); dr.appendChild(el("span", "muted", "/")); dr.appendChild(bb);
  dr.appendChild(el("span", "spacer"));
  if (me && me.stack === 0) {
    const rb = el("button", "", `Rebuy ${fmt(s.settings.starting_stack)}`); rb.onclick = () => send({ type: "rebuy" }); dr.appendChild(rb);
  }
  const hide = el("button", "ghost", "View table"); hide.onclick = () => { modalHidden = true; renderModal(); };
  dr.appendChild(hide);
  const deal = el("button", "primary big", "Shuffle & deal");
  const playable = s.seats.filter(x => !x.empty && x.stack > 0).length;
  deal.disabled = !combo.ok || playable < 2;
  if (playable < 2) deal.title = s.cannot_start_reason;
  deal.onclick = () => send({ type: "start_hand", ...selection(), variant_id: preset.id, options: resolved,
    small_blind: +sb.value, big_blind: +bb.value });
  dr.appendChild(deal);
  box.appendChild(dr);
  if (playable < 2) box.appendChild(el("div", "muted", "You need at least 2 players: invite a friend or add a bot."));
  fitModal();
}

// ------------------------------------------------------------- animations
function center(r) { return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
function captureRects() {
  const out = { bets: {}, avatars: {}, pot: null, keys: new Set() };
  document.querySelectorAll("[data-bet]").forEach(e => { if (e.children.length) out.bets[e.dataset.bet] = e.getBoundingClientRect(); });
  document.querySelectorAll("[data-key]").forEach(e => out.keys.add(e.dataset.key + (e.dataset.code || "")));
  const pot = $("pot-main"); if (pot) out.pot = pot.getBoundingClientRect();
  return out;
}
function flyChips(from, to, amount, delay = 0) {
  const fx = $("fx");
  chipsFor(amount, 3).forEach((d, k) => {
    const c = el("div", "chip fxchip " + (d ? "d" + d : "odd"));
    c.style.left = from.x + "px"; c.style.top = from.y + "px";
    fx.appendChild(c);
    c.animate([{ transform: "translate(0,0)", opacity: 1 }, { transform: `translate(${to.x - from.x}px, ${to.y - from.y}px)`, opacity: 1 }],
      { duration: 520, delay: delay + k * 70, easing: "cubic-bezier(.3,.7,.3,1)", fill: "both" }).onfinish = () => c.remove();
  });
}
// Phones and short screens: seats are small, so ordinary moves aren't popped
// up (each seat's tag shows its last move) and the rest sit ON the seat.
const COMPACT = matchMedia("(max-width: 899px) and (orientation: portrait), (max-width: 639px), "
  + "(orientation: landscape) and (max-height: 600px)");
const PLAIN_MOVES = new Set(["fold", "check", "call", "bet", "raise", "blind", "allin"]);
function bubble(seat, text, cls) {
  if (COMPACT.matches && PLAIN_MOVES.has(cls)) return;
  const av = document.querySelector(`[data-avatar="${seat}"]`); if (!av) return;
  const r = av.getBoundingClientRect();
  const who = state && state.seats[seat] ? (seat === state.you ? "You" : nameOf(seat)) : "";
  const b = el("div", "bubble " + cls + (COMPACT.matches ? " center" : ""),
    (who ? `<span class="who">${esc(who)}</span>` : "") + esc(text));
  // keep it on screen (the top row of players sits near the top edge)
  const half = COMPACT.matches ? 90 : 120;
  b.style.left = Math.min(innerWidth - half, Math.max(half, r.left + r.width / 2)) + "px";
  b.style.top = (COMPACT.matches ? r.top + r.height / 2 : Math.max(64, r.top - 6)) + "px";
  $("fx").appendChild(b); setTimeout(() => b.remove(), 3600);
}
function banner(text, cls = "") {
  document.querySelectorAll("#fx .banner").forEach(x => x.remove());   // one at a time
  if (!$("modal").hidden) return;                                       // a panel is open: no banners on top
  const b = el("div", "banner " + cls, esc(text)); $("fx").appendChild(b);
  setTimeout(() => b.remove(), cls.includes("big") ? 2600 : 1800);
}
function flash() {           // gold flash for monster hands
  const f = el("div", "flash"); $("fx").appendChild(f); setTimeout(() => f.remove(), 900);
}
function shake() {           // the table jolts for an all-in
  $("screen").animate([{ translate: "0 0" }, { translate: "-6px 2px" }, { translate: "6px -2px" },
    { translate: "-4px 1px" }, { translate: "3px 0" }, { translate: "0 0" }], { duration: 420 });
}

// ------------------------------------------------------------- sound
// Small synthesized sounds (no files). Off/on with the speaker button.
let soundOn = true;
try { soundOn = localStorage.getItem("pokrr-sound") !== "off"; } catch {}
let actx = null;
function tone(freq, dur, type = "sine", vol = 0.08, when = 0) {
  if (!soundOn) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const t = actx.currentTime + when, o = actx.createOscillator(), g = actx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(actx.destination); o.start(t); o.stop(t + dur);
  } catch {}
}
function sfx(kind) {
  if (kind === "chips") { tone(2200, 0.05, "triangle", 0.05); tone(2600, 0.05, "triangle", 0.04, 0.05); }
  else if (kind === "card") tone(900, 0.04, "triangle", 0.03);
  else if (kind === "flip") { tone(500, 0.06, "square", 0.03); tone(750, 0.08, "triangle", 0.04, 0.05); }
  else if (kind === "allin") { tone(110, 0.5, "sawtooth", 0.07); tone(82, 0.6, "sine", 0.1, 0.05); }
  else if (kind === "win") [523, 659, 784, 1047].forEach((f, k) => tone(f, 0.22, "triangle", 0.07, k * 0.11));
  else if (kind === "turn") tone(880, 0.12, "sine", 0.05);
}
function updateSoundBtn() { $("sound-btn").textContent = soundOn ? "🔊" : "🔇"; }
$("sound-btn").onclick = () => {
  soundOn = !soundOn; updateSoundBtn();
  try { localStorage.setItem("pokrr-sound", soundOn ? "on" : "off"); } catch {}
  if (soundOn) sfx("turn");
};
updateSoundBtn();

function runEffects(rects) {
  const s = state, p = prev;
  const newHand = !p || p.hand_no !== s.hand_no;
  const deckR = $("deck").getBoundingClientRect(), deckC = center(deckR);
  let dealDelay = 0;
  if (newHand && s.hand_active) {
    $("deck").classList.remove("shuffling"); void $("deck").offsetWidth; $("deck").classList.add("shuffling");
    dealDelay = 900;
  }
  // deal / reveal: every card element not on screen before flies from the deck
  const fresh = [...document.querySelectorAll("[data-key]")].filter(e => newHand || !rects.keys.has(e.dataset.key + (e.dataset.code || "")));
  fresh.sort((a, b) => order(a) - order(b));
  fresh.forEach((e, k) => {
    const r = e.getBoundingClientRect(), c = center(r);
    const wasBack = !newHand && e.dataset.code && rects.keys.has(e.dataset.key);
    if (wasBack) {          // a face-down card turned over (showdown)
      e.animate([{ transform: "rotateY(90deg)" }, { transform: "none" }], { duration: 300, delay: k * 40, fill: "backwards" });
      return;
    }
    // screen distance -> layout distance (the game screen is scaled)
    e.animate([{ transform: `translate(${(deckC.x - c.x) / SCALE}px, ${(deckC.y - c.y) / SCALE}px) scale(.6) rotate(-8deg)`, opacity: .9 },
               { transform: "none", opacity: 1 }],
      { duration: 420, delay: dealDelay + k * (newHand ? 55 : 110), easing: "cubic-bezier(.2,.8,.3,1)", fill: "backwards" });
  });
  if (fresh.length) sfx("card");
  if (newHand) return;
  if (s.legal && !p.legal) sfx("turn");                      // your turn
  // chips: new bets fly from the player to their bet spot
  s.seats.forEach((x, i) => {
    if (x.empty) return;
    const before = p.seats[i]?.bet || 0;
    if (x.bet > before) {
      const av = document.querySelector(`[data-avatar="${i}"]`), spot = document.querySelector(`[data-bet="${i}"]`);
      if (av && spot) flyChips(center(av.getBoundingClientRect()), center(spot.getBoundingClientRect()), x.bet - before);
    }
  });
  // bets collected into the pot at the end of a street
  const potEl = $("pot-main");
  const sumBets = (v) => v.seats.reduce((a, x) => a + (x.bet || 0), 0);
  const collected = sumBets(p) > 0 && sumBets(s) === 0;     // street over: bets swept in
  if (potEl && collected) {
    const to = center(potEl.getBoundingClientRect());
    p.seats.forEach((x, i) => { if (x.bet > 0 && rects.bets[i]) flyChips(center(rects.bets[i]), to, x.bet, 150); });
  }
  // what just happened: bubbles over players + street banners
  const newItems = s.history.slice(p.history.length);
  for (const h of newItems) {
    if (h.kind === "action" || h.kind === "blind") {
      const a = h.action;
      const text = h.all_in ? `All-in ${fmt(h.amount)}` : a === "fold" ? "Fold" : a === "check" ? "Check"
        : a === "call" ? `Call ${fmt(h.amount)}` : a === "bet" ? `Bet ${fmt(h.amount)}` : a === "raise" ? `Raise to ${fmt(h.amount)}`
        : a === "blind" ? (h.text.includes("small") ? `Small blind ${fmt(h.amount)}` : `Big blind ${fmt(h.amount)}`) : h.text;
      bubble(h.seat, text, h.all_in ? "allin" : a);
      if (h.all_in) { banner("All-in!", "allin-banner"); shake(); sfx("allin"); }
      else if (a === "bet" || a === "raise" || a === "call") sfx("chips");
    } else if (h.kind === "board") {
      if (!s.result) banner(h.street);                    // hand over: the showdown takes over
      sfx("card");
    } else if (h.kind === "declare" && h.seat == null) {
      banner("Showdown");
    } else if (h.kind === "redriver") {
      if (h.text.startsWith("RED")) { banner("🔴 Red river! Another one's coming", "big"); sfx("allin"); }
      else banner("⚫ Black river — that's the last");
    } else if (h.kind === "dice") {
      banner(h.old ? `🎲 Rolled ${h.die}: ${h.old.replace("T", "10")} → ${h.new.replace("T", "10")}` : `🎲 Rolled ${h.die}: no change`, "big");
      sfx("flip");
    } else if (h.kind === "hit" && h.seat != null) {
      bubble(h.seat, h.text.includes("stands") ? "Stand" : "Hit!", h.text.includes("stands") ? "check" : "call");
      sfx("card");
    } else if (h.kind === "bust") {
      bubble(h.seat, "BUST!", "fold bust"); shake(); sfx("allin");
    } else if (h.kind === "buy") {
      bubble(h.seat, `Buys ${h.cards[0].replace("T", "10")} · ${fmt(h.amount)}`, "bet"); sfx("chips");
    } else if (h.kind === "discard") {
      // shown by the pacer (a card flies off the seat) before this update
    } else if (h.kind === "bounty") {
      flash(); banner("💰 7-2 BOUNTY!", "big gold"); sfx("win");
    } else if (h.kind === "pass" && h.text.startsWith("Pineapple")) {
      banner("🍍 Pineapple — throw away");
    } else if (h.kind === "market" && h.text.startsWith("The market opens")) {
      banner("📈 The market is open");
    } else if (h.kind === "auction") {
      if (h.text.startsWith("JOKER AUCTION")) { banner("🃏 Joker auction!", "big gold"); sfx("flip"); }
      else if (h.seat != null) { flash(); bubble(h.seat, `Wins the joker · ${fmt(h.amount)}`, "win"); sfx("win"); }
    } else if (h.kind === "bid" && h.seat != null) {
      bubble(h.seat, h.amount ? `Bids ${fmt(h.amount)}` : "Drops out", h.amount ? "raise" : "fold");
      if (h.amount) sfx("chips");
    }
  }
  // hand over without a showdown (everyone folded): chips go to the winner now
  // (showdowns celebrate at the end of the one-by-one reveal)
  if (s.result && !p.result && !s.result.showdown) celebrate(s);
}
function order(e) {   // deal order: round by round, then seat
  const k = e.dataset.key;
  const m = /^s(\d+)-(\d+)$/.exec(k);
  if (m) {
    const s = state, n = s.seats.length, btn = s.button ?? 0;
    return (+m[2]) * 100 + ((+m[1] - btn - 1 + n) % n);
  }
  return 10000 + [...document.querySelectorAll("[data-key]")].indexOf(e);
}

fitScreen();
connect();

// The POKRR logo opens the website (games, rules, guides). At a table, ask first;
// your seat is kept, so the same link brings you back.
$("home-link").onclick = (ev) => {
  if (roomInfo && !confirm("Open the POKRR home page? Your seat is kept: come back with your table link.")) ev.preventDefault();
};
