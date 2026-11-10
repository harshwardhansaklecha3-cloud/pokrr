"""Variation definitions: game families (what the dealer sees) plus the
original named presets (kept so older saved choices and tests still work)."""
from . import presets as _presets
from .base import BoardGroup, HandExplanation, HandRow, Stage, Variant, VariantError
from .families import FAMILIES
from .presets import PRESETS, get_preset

HOLDEM = _presets.build_variant("holdem")          # classic: any 5 of 7

for _p in PRESETS.values():                        # every legacy combo must be valid
    for _c in _p.combos():
        _p.make(_c)
for _f in FAMILIES.values():                       # every family default must be valid
    _f.make({})


def build_variant(variant_id: str, options: dict | None = None) -> Variant:
    if variant_id in FAMILIES:
        return FAMILIES[variant_id].make(options)
    return _presets.build_variant(variant_id, options)


def get_variant(variant_id: str, options: dict | None = None) -> Variant:
    return build_variant(variant_id, options)


def catalogue(player_count: int | None = None) -> list[dict]:
    """The dealer's menu: each family with its adjustable options."""
    return [{"id": f.id, "name": f.name, "pitch": f.pitch,
             "options": [{"key": o.key, "label": o.label, "default": o.default,
                          "choices": [{"value": a, "label": b} for a, b in o.choices]}
                         for o in f.options]}
            for f in FAMILIES.values()]


__all__ = ["PRESETS", "FAMILIES", "build_variant", "catalogue", "get_preset", "get_variant",
           "Variant", "Stage", "BoardGroup", "HandRow", "HandExplanation",
           "VariantError", "HOLDEM"]
