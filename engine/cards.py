"""Decks and the shoe that deals from them.

PokerKit shuffles with Python's non-secure ``random`` module, so the engine
never lets PokerKit pick cards. Every card dealt comes from a ``Shoe``.
"""
from __future__ import annotations

import random
import secrets
from collections.abc import Iterable, Sequence

from pokerkit import Card, Deck

STANDARD_52: tuple[Card, ...] = tuple(Deck.STANDARD)
assert len(STANDARD_52) == 52 and len(set(STANDARD_52)) == 52


class DeckExhausted(RuntimeError):
    """Raised when more cards are requested than remain in the shoe."""


def card_str(card: Card) -> str:
    """'As', 'Td', ... — PokerKit's repr of a card."""
    return repr(card)


def parse_cards(text: str) -> list[Card]:
    return list(Card.parse(text))


class Shoe:
    """A single shuffled deck for one hand.

    ``rng`` defaults to a cryptographically secure generator. Tests pass a
    seeded ``random.Random`` or use :meth:`stacked` to fix the exact order.
    """

    def __init__(self, cards: Iterable[Card], rng: random.Random | None = None):
        self._cards = list(cards)
        if len(set(self._cards)) != len(self._cards):
            raise ValueError("deck contains duplicate cards")
        (rng or secrets.SystemRandom()).shuffle(self._cards)
        self._next = 0

    @classmethod
    def stacked(cls, order: Sequence[Card]) -> "Shoe":
        """A shoe that deals exactly ``order`` (first card first). Tests only."""
        shoe = cls.__new__(cls)
        shoe._cards = list(order)
        if len(set(shoe._cards)) != len(shoe._cards):
            raise ValueError("stacked deck contains duplicate cards")
        shoe._next = 0
        return shoe

    @property
    def remaining(self) -> int:
        return len(self._cards) - self._next

    def draw(self, n: int = 1) -> list[Card]:
        if n > self.remaining:
            raise DeckExhausted(f"needed {n} card(s), only {self.remaining} left")
        out = self._cards[self._next:self._next + n]
        self._next += n
        return out
