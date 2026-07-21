"""PokeRogue -- Archipelago world definition.

Targets the standalone offline desktop build of PokeRogue (Electron), patched
with the Archipelago bridge shipped alongside this apworld. See docs/setup_en.md.
"""

import logging
from typing import Any, ClassVar

from BaseClasses import Item, ItemClassification, Region, Tutorial
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch_subprocess

from .Items import (
    FILLER_ITEMS,
    ITEM_CLASSIFICATION,
    ITEM_GROUPS,
    ITEM_NAME_TO_ID,
    LEVEL_CAP_TIERS,
    PROGRESSIVE_LEVEL_CAP_ITEM,
    USEFUL_FILLER_NAMES,
    PokeRogueItem,
    species_item_name,
)
from .Locations import (
    LOCATION_GROUPS,
    LOCATION_NAME_TO_ID,
    PokeRogueLocation,
    build_wave_locations,
    dexsanity_location_name,
)
from .Options import PokeRogueOptions
from .Species import SOURCE_GAME_VERSION, STARTER_SPECIES, SpeciesInfo

logger = logging.getLogger("PokeRogue")

MENU = "Menu"

#: How much of the full species catalog to draw starting species from,
#: weighted toward lower cost so an opening run is actually playable. Not
#: player-facing -- just keeps a fresh game from handing out three
#: cost-10 legendaries as your only options.
STARTING_SPECIES_CANDIDATE_MULTIPLIER = 8
STARTING_SPECIES_CANDIDATE_MINIMUM = 40


def _launch_client(*args: str) -> None:
    """Entry point used by the Archipelago Launcher."""
    from .Client import launch

    launch_subprocess(launch, name="PokeRogueClient", args=args)


components.append(
    Component(
        "PokeRogue Client",
        func=_launch_client,
        component_type=Type.CLIENT,
        description="Bridges a patched PokeRogue Offline build to Archipelago.",
    )
)


class PokeRogueWeb(WebWorld):
    theme = "ocean"
    tutorials = [
        Tutorial(
            "Multiworld Setup Guide",
            "A guide to setting up PokeRogue for Archipelago multiworld.",
            "English",
            "setup_en.md",
            "setup/en",
            ["ap-pokerogue"],
        )
    ]


class PokeRogueWorld(World):
    """PokeRogue is a roguelite Pokemon fangame. Fight through 200 waves of
    Classic mode, unlocking the right to use each species from the multiworld."""

    game = "PokeRogue"
    web = PokeRogueWeb()
    options_dataclass = PokeRogueOptions
    options: PokeRogueOptions
    topology_present = False
    origin_region_name = MENU

    item_name_to_id = ITEM_NAME_TO_ID
    location_name_to_id = LOCATION_NAME_TO_ID
    item_name_groups = ITEM_GROUPS
    location_name_groups = LOCATION_GROUPS

    required_client_version: ClassVar[tuple[int, int, int]] = (0, 5, 0)

    def __init__(self, multiworld, player: int):
        super().__init__(multiworld, player)
        #: Species that can ever be unlocked this seed. Full 572-species
        #: catalog when dexsanity is on; just the starting species otherwise,
        #: since there is nothing else in the item pool to grow it with.
        self.species_pool: list[SpeciesInfo] = []
        #: Species granted for free at game start.
        self.starting_species: list[SpeciesInfo] = []
        self.wave_locations: list = []
        self.goal_wave: int = 200

    # ------------------------------------------------------------------ setup

    def generate_early(self) -> None:
        opts = self.options
        self.goal_wave = opts.goal_wave.wave
        interval = opts.wave_check_interval.value
        self.wave_locations = build_wave_locations(interval, self.goal_wave)

        starting = min(opts.starting_species.value, len(STARTER_SPECIES))

        # Dexsanity on: every species is in play, full stop -- no pool size to
        # tune, since every species brings its own location with it.
        #
        # Dexsanity off: nothing grows the roster after the start (see
        # create_items), so there is no pool at all beyond the starting
        # species themselves.
        self.species_pool = list(STARTER_SPECIES) if opts.dexsanity else []

        self.starting_species = self._pick_starting_species(starting)
        for species in self.starting_species:
            self.multiworld.push_precollected(
                self.create_item(species_item_name(species.display))
            )

    def _pick_starting_species(self, count: int) -> list[SpeciesInfo]:
        """Sample starting species with a light preference for low cost."""
        rng = self.random
        candidates = sorted(STARTER_SPECIES, key=lambda s: s.cost)
        window = max(count * STARTING_SPECIES_CANDIDATE_MULTIPLIER, STARTING_SPECIES_CANDIDATE_MINIMUM)
        candidates = candidates[:window] if len(candidates) >= window else candidates
        return rng.sample(candidates, count)

    # ---------------------------------------------------------------- regions

    def create_regions(self) -> None:
        # Every location hangs directly off Menu with no access rules. AP's
        # logic layer does not need to model wave ordering -- the game itself
        # only lets you reach wave 100 after wave 90, so gating region access
        # on some proxy (species count, item count) would just add a way for
        # generation to soft-lock without adding real logic.
        menu = Region(MENU, self.player, self.multiworld)
        self.multiworld.regions.append(menu)

        for wave_loc in self.wave_locations:
            loc = PokeRogueLocation(self.player, wave_loc.name, wave_loc.address, menu)
            menu.locations.append(loc)

        if self.options.dexsanity:
            for species in self.species_pool:
                name = dexsanity_location_name(species.display)
                loc = PokeRogueLocation(self.player, name, LOCATION_NAME_TO_ID[name], menu)
                menu.locations.append(loc)

        victory = PokeRogueLocation(self.player, "Classic Mode Victory", None, menu)
        victory.place_locked_item(
            PokeRogueItem("Victory", ItemClassification.progression, None, self.player)
        )
        menu.locations.append(victory)

    def set_rules(self) -> None:
        self.multiworld.completion_condition[self.player] = lambda state: state.has(
            "Victory", self.player
        )

    # ------------------------------------------------------------------ items

    def create_item(self, name: str) -> Item:
        return PokeRogueItem(
            name,
            ITEM_CLASSIFICATION.get(name, ItemClassification.filler),
            ITEM_NAME_TO_ID[name],
            self.player,
        )

    def create_items(self) -> None:
        pool: list[Item] = []
        precollected = {s.species_id for s in self.starting_species}

        if self.options.dexsanity:
            for species in self.species_pool:
                if species.species_id in precollected:
                    continue
                pool.append(self.create_item(species_item_name(species.display)))
        else:
            # No species growth in this mode -- every wave check instead
            # raises the Classic-mode level cap by one tier.
            pool.extend(
                self.create_item(PROGRESSIVE_LEVEL_CAP_ITEM) for _ in self.wave_locations
            )

        total_locations = len(self.multiworld.get_unfilled_locations(self.player))
        remaining = total_locations - len(pool)

        if remaining < 0:
            logger.warning(
                "PokeRogue (%s): trimmed %d items that did not fit.",
                self.player_name,
                -remaining,
            )
            pool = pool[:total_locations]
            remaining = 0

        for _ in range(remaining):
            pool.append(self.create_item(self.get_filler_item_name()))

        self.multiworld.itempool += pool

    def get_filler_item_name(self) -> str:
        if self.options.split_dexsanity_rewards:
            return self.random.choice(USEFUL_FILLER_NAMES)
        names = [f.name for f in FILLER_ITEMS]
        weights = [f.weight for f in FILLER_ITEMS]
        return self.random.choices(names, weights=weights, k=1)[0]

    # ------------------------------------------------------------- slot data

    def fill_slot_data(self) -> dict[str, Any]:
        """Everything the game-side bridge needs to enforce the rules locally."""
        dexsanity_on = bool(self.options.dexsanity)
        return {
            "goal_wave": self.goal_wave,
            "wave_check_interval": self.options.wave_check_interval.value,
            "dexsanity": dexsanity_on,
            "death_link": bool(self.options.death_link),
            "game_version": SOURCE_GAME_VERSION,
            # numeric SpeciesId -> AP location id, for catch events
            "dexsanity_species": (
                {
                    str(s.species_id): LOCATION_NAME_TO_ID[dexsanity_location_name(s.display)]
                    for s in self.species_pool
                }
                if dexsanity_on
                else {}
            ),
            # AP item id -> numeric SpeciesId, for unlock grants
            "species_items": {
                str(ITEM_NAME_TO_ID[species_item_name(s.display)]): s.species_id
                for s in STARTER_SPECIES
            },
            # Every species the game gate should ever manage. Anything absent
            # from this list is left fully alone (not a starter at all).
            "all_starter_species": [s.species_id for s in STARTER_SPECIES],
            "pool_species": [s.species_id for s in self.species_pool],
            "starting_species": [s.species_id for s in self.starting_species],
            "wave_locations": {str(w.wave): w.address for w in self.wave_locations},
            # Progressive Level Cap: item id to count copies of, and the tier
            # table to look the count up against. Both None/empty when
            # dexsanity is on, since the cap is unrestricted in that mode.
            "progressive_level_cap_item": (
                None if dexsanity_on else ITEM_NAME_TO_ID[PROGRESSIVE_LEVEL_CAP_ITEM]
            ),
            "level_cap_tiers": [] if dexsanity_on else list(LEVEL_CAP_TIERS),
        }
