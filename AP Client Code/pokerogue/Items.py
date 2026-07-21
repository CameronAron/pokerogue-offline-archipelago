"""Item definitions for the PokeRogue apworld.

ID layout (item namespace):
    BASE + <species_id>        species unlock items  (species_id <= 8901)
    BASE + 90000 + <n>         filler / trap items
    BASE + 91000                Progressive Level Cap (dexsanity-off mode only)
"""

from typing import NamedTuple

from BaseClasses import Item, ItemClassification

from .Species import STARTER_SPECIES

BASE_ID = 77_770_000
FILLER_OFFSET = 90_000
PROGRESSIVE_OFFSET = 91_000

#: name of the single progressive item used when dexsanity is off.
PROGRESSIVE_LEVEL_CAP_ITEM = "Progressive Level Cap"
PROGRESSIVE_LEVEL_CAP_ID = BASE_ID + PROGRESSIVE_OFFSET

#: Classic mode's vanilla level cap, one entry per 10-wave block, taken from
#: https://wiki.pokerogue.net/gameplay:modes:classic . Tier 1 (level 10) is
#: always available for free; each copy of Progressive Level Cap received
#: raises the effective cap to the next tier, up to level 200 at tier 20.
LEVEL_CAP_TIERS: tuple[int, ...] = (
    10, 16, 24, 32, 38, 48, 56, 64, 74, 84,
    94, 104, 114, 126, 138, 150, 162, 174, 188, 200,
)


class PokeRogueItem(Item):
    game = "PokeRogue"


class FillerDef(NamedTuple):
    name: str
    classification: ItemClassification
    #: Relative weight used when padding the pool with filler.
    weight: int


#: Consumables and quality-of-life grants the client applies to the live run.
#: These are deliberately modest -- PokeRogue is already a roguelite economy and
#: handing out too much trivialises the wave milestones.
FILLER_ITEMS: tuple[FillerDef, ...] = (
    FillerDef("Rare Candy", ItemClassification.filler, 20),
    FillerDef("Poke Ball Pack", ItemClassification.filler, 18),
    FillerDef("Great Ball Pack", ItemClassification.filler, 14),
    FillerDef("Ultra Ball Pack", ItemClassification.filler, 8),
    FillerDef("Rogue Ball Pack", ItemClassification.filler, 3),
    FillerDef("Master Ball", ItemClassification.useful, 1),
    FillerDef("Money Pouch", ItemClassification.filler, 16),
    FillerDef("Egg Voucher", ItemClassification.filler, 8),
    FillerDef("Egg Voucher Plus", ItemClassification.useful, 3),
    FillerDef("Exp Charm", ItemClassification.useful, 4),
    FillerDef("Healing Charm", ItemClassification.useful, 3),
    FillerDef("Lure", ItemClassification.filler, 6),
    FillerDef("Berry Bundle", ItemClassification.filler, 10),
    FillerDef("Nothing", ItemClassification.filler, 6),
)

#: Filler that leans consumable-heavy, used when split_dexsanity_rewards is on.
USEFUL_FILLER_NAMES = (
    "Rare Candy",
    "Ultra Ball Pack",
    "Exp Charm",
    "Healing Charm",
    "Egg Voucher Plus",
    "Berry Bundle",
)

#: Strictly ItemClassification.filler entries -- no useful/progression flags.
#: Excluded locations (see dexsanity_exclude_above_cost) can only ever hold a
#: plain filler item, so __init__.py uses this list to guarantee enough of
#: them exist for however many locations get excluded, rather than leaving it
#: to chance via the normal weighted filler roll (which includes useful
#: entries like Master Ball that an excluded location cannot legally hold).
PURE_FILLER_NAMES = tuple(f.name for f in FILLER_ITEMS if f.classification == ItemClassification.filler)


def species_item_name(display: str) -> str:
    return f"{display} Unlock"


#: name -> id for every species unlock item.
SPECIES_ITEMS: dict[str, int] = {
    species_item_name(s.display): BASE_ID + s.species_id for s in STARTER_SPECIES
}

#: name -> id for filler.
FILLER_ITEM_IDS: dict[str, int] = {
    f.name: BASE_ID + FILLER_OFFSET + i for i, f in enumerate(FILLER_ITEMS)
}

#: The full item_name_to_id table exposed to Archipelago.
ITEM_NAME_TO_ID: dict[str, int] = {
    **SPECIES_ITEMS,
    **FILLER_ITEM_IDS,
    PROGRESSIVE_LEVEL_CAP_ITEM: PROGRESSIVE_LEVEL_CAP_ID,
}

#: name -> classification, for everything above.
#
# Species unlocks are `useful` rather than `progression`: nothing in this
# world's logic (a single flat region, no access rules) actually depends on
# having a species unlocked to reach anything, so `progression` would
# overstate their importance to the fill algorithm and to progression
# balancing. `useful` still protects them from excluded/unreachable
# locations and marks them desirable, without the false claim.
#
# Progressive Level Cap uses `progression | useful` -- AP has no literal tier
# above `progression`, but this combined flag is described in BaseClasses.py
# itself as "an especially useful progression item" and is the strongest
# classification the fill algorithm actually offers, which is the closest
# real equivalent to "mark this more important than plain progression".
ITEM_CLASSIFICATION: dict[str, ItemClassification] = {
    **{n: ItemClassification.useful for n in SPECIES_ITEMS},
    **{f.name: f.classification for f in FILLER_ITEMS},
    PROGRESSIVE_LEVEL_CAP_ITEM: ItemClassification.progression | ItemClassification.useful,
}

#: item name -> numeric SpeciesId, for the client to act on.
ITEM_NAME_TO_SPECIES_ID: dict[str, int] = {
    species_item_name(s.display): s.species_id for s in STARTER_SPECIES
}

ITEM_GROUPS: dict[str, set[str]] = {
    "Species Unlocks": set(SPECIES_ITEMS),
    "Filler": set(FILLER_ITEM_IDS),
    "Poke Balls": {
        "Poke Ball Pack",
        "Great Ball Pack",
        "Ultra Ball Pack",
        "Rogue Ball Pack",
        "Master Ball",
    },
    "Vouchers": {"Egg Voucher", "Egg Voucher Plus"},
    "Progression Pacing": {PROGRESSIVE_LEVEL_CAP_ITEM},
}

#: Per-generation convenience groups, e.g. "Generation 1 Species".
for _gen in range(1, 10):
    ITEM_GROUPS[f"Generation {_gen} Species"] = {
        species_item_name(s.display) for s in STARTER_SPECIES if s.generation == _gen
    }
