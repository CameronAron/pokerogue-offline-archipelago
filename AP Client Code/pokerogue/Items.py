"""Item definitions for the PokeRogue apworld.

ID layout (item namespace):
    BASE + <species_id>        species unlock items  (species_id <= 8901)
    BASE + 90000 + <n>         filler / trap items
"""

from typing import NamedTuple

from BaseClasses import Item, ItemClassification

from .Species import STARTER_SPECIES

BASE_ID = 77_770_000
FILLER_OFFSET = 90_000


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
ITEM_NAME_TO_ID: dict[str, int] = {**SPECIES_ITEMS, **FILLER_ITEM_IDS}

#: name -> classification, for everything above.
ITEM_CLASSIFICATION: dict[str, ItemClassification] = {
    **{n: ItemClassification.progression for n in SPECIES_ITEMS},
    **{f.name: f.classification for f in FILLER_ITEMS},
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
}

#: Per-generation convenience groups, e.g. "Generation 1 Species".
for _gen in range(1, 10):
    ITEM_GROUPS[f"Generation {_gen} Species"] = {
        species_item_name(s.display) for s in STARTER_SPECIES if s.generation == _gen
    }
