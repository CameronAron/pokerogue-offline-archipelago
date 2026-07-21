"""PokeRogue -- Archipelago world definition.

Targets the standalone offline desktop build of PokeRogue (Electron), patched
with the Archipelago bridge shipped alongside this apworld. See docs/setup_en.md.
"""

import logging
import math
from typing import Any, ClassVar

from BaseClasses import Item, ItemClassification, Region, Tutorial
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch_subprocess

from .Items import (
    FILLER_ITEMS,
    ITEM_CLASSIFICATION,
    ITEM_GROUPS,
    ITEM_NAME_TO_ID,
    ITEM_NAME_TO_SPECIES_ID,
    USEFUL_FILLER_NAMES,
    PokeRogueItem,
    species_item_name,
)
from .Locations import (
    LOCATION_GROUPS,
    LOCATION_NAME_TO_ID,
    LOCATION_NAME_TO_SPECIES_ID,
    PokeRogueLocation,
    build_wave_locations,
    dexsanity_location_name,
)
from .Options import PokeRogueOptions
from .Species import SOURCE_GAME_VERSION, STARTER_SPECIES, SpeciesInfo

logger = logging.getLogger("PokeRogue")

#: Region names.
MENU = "Menu"
EARLY = "Early Waves"
MID = "Mid Waves"
LATE = "Late Waves"

#: Species unlocks required to enter each region. Kept small on purpose: a
#: PokeRogue party is six Pokemon, so needing far more than a couple of teams'
#: worth would gate progress behind grinding rather than behind the multiworld.
MID_SPECIES_REQUIRED = 6
LATE_SPECIES_REQUIRED = 12

#: Starter-cost brackets used to spread dexsanity checks across regions.
#: Cheap mons show up in the first few biomes; legendaries realistically do not
#: appear until the run is well underway.
CHEAP_MAX_COST = 4
MID_MAX_COST = 7


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
        #: Species rolled into this slot's pool.
        self.species_pool: list[SpeciesInfo] = []
        #: Species granted for free at game start.
        self.starting_species: list[SpeciesInfo] = []
        #: Wave milestone locations actually used.
        self.wave_locations: list = []
        self.goal_wave: int = 200

    # ------------------------------------------------------------------ setup

    def generate_early(self) -> None:
        opts = self.options
        self.goal_wave = opts.goal_wave.wave
        interval = opts.wave_check_interval.value

        self.wave_locations = build_wave_locations(interval, self.goal_wave)
        wave_count = len(self.wave_locations)

        requested = opts.species_pool_size.value
        starting = min(opts.starting_species.value, requested)

        # An item must exist for every location and vice versa. Locations are
        # wave milestones plus (optionally) one dexsanity check per pooled
        # species. Pre-collected starting species do not consume a location.
        #
        #   dexsanity on : locations = waves + pool  ->  pool is unconstrained,
        #                  since each extra species brings its own location.
        #   dexsanity off: locations = waves only    ->  the placeable unlocks
        #                  are capped by the wave count.
        if opts.dexsanity:
            pool_size = requested
        else:
            # Reserve a slice of the wave checks for filler so the seed is not
            # 100% species unlocks with no consumables at all.
            placeable = max(1, wave_count - max(1, wave_count // 5))
            pool_size = min(requested, placeable + starting)
            if pool_size < requested:
                logger.warning(
                    "PokeRogue (%s): dexsanity is off, so this slot only has %d "
                    "locations. species_pool_size was reduced from %d to %d. "
                    "Turn dexsanity on, or lower wave_check_interval, for a "
                    "larger roster.",
                    self.player_name,
                    wave_count,
                    requested,
                    pool_size,
                )

        pool_size = max(pool_size, starting, 1)
        self.species_pool = self._roll_species(pool_size)
        self.starting_species = self.species_pool[:starting]

        for species in self.starting_species:
            self.multiworld.push_precollected(
                self.create_item(species_item_name(species.display))
            )

    def _roll_species(self, count: int) -> list[SpeciesInfo]:
        """Choose `count` species according to the cost-bias option."""
        bias = self.options.starter_cost_bias
        rng = self.random
        count = min(count, len(STARTER_SPECIES))

        if bias == 0:  # any
            return rng.sample(list(STARTER_SPECIES), count)

        cheap = [s for s in STARTER_SPECIES if s.cost <= CHEAP_MAX_COST]
        mid = [s for s in STARTER_SPECIES if CHEAP_MAX_COST < s.cost <= MID_MAX_COST]
        pricey = [s for s in STARTER_SPECIES if s.cost > MID_MAX_COST]

        if bias == 1:  # cheap
            weights = (0.75, 0.20, 0.05)
        else:  # balanced
            weights = (0.55, 0.30, 0.15)

        chosen: list[SpeciesInfo] = []
        for bucket, weight in zip((cheap, mid, pricey), weights):
            take = min(len(bucket), int(round(count * weight)))
            chosen.extend(rng.sample(bucket, take))

        # Top up from whatever is left if rounding left us short.
        if len(chosen) < count:
            picked = {s.species_id for s in chosen}
            remainder = [s for s in STARTER_SPECIES if s.species_id not in picked]
            chosen.extend(rng.sample(remainder, count - len(chosen)))

        chosen = chosen[:count]
        rng.shuffle(chosen)
        # Guarantee the free starting species are actually usable early on.
        chosen.sort(key=lambda s: s.cost)
        head, tail = chosen[: self.options.starting_species.value], chosen[self.options.starting_species.value :]
        rng.shuffle(tail)
        return head + tail

    # ---------------------------------------------------------------- regions

    def create_regions(self) -> None:
        menu = Region(MENU, self.player, self.multiworld)
        early = Region(EARLY, self.player, self.multiworld)
        mid = Region(MID, self.player, self.multiworld)
        late = Region(LATE, self.player, self.multiworld)
        self.multiworld.regions.extend([menu, early, mid, late])

        menu.connect(early)
        early.connect(
            mid,
            rule=lambda state: self._has_species(state, MID_SPECIES_REQUIRED),
        )
        mid.connect(
            late,
            rule=lambda state: self._has_species(state, LATE_SPECIES_REQUIRED),
        )

        # Wave milestones land in a region based on how deep they are.
        third = self.goal_wave / 3
        for wave_loc in self.wave_locations:
            region = early if wave_loc.wave <= third else mid if wave_loc.wave <= third * 2 else late
            loc = PokeRogueLocation(self.player, wave_loc.name, wave_loc.address, region)
            region.locations.append(loc)

        # Dexsanity checks land in a region based on starter cost, as a proxy
        # for how deep into a run that species realistically shows up.
        if self.options.dexsanity:
            for species in self.species_pool:
                region = (
                    early
                    if species.cost <= CHEAP_MAX_COST
                    else mid
                    if species.cost <= MID_MAX_COST
                    else late
                )
                name = dexsanity_location_name(species.display)
                loc = PokeRogueLocation(self.player, name, LOCATION_NAME_TO_ID[name], region)
                region.locations.append(loc)

        # The goal itself is an event, not a real check.
        victory_region = late if self.goal_wave > third * 2 else mid
        victory = PokeRogueLocation(self.player, "Classic Mode Victory", None, victory_region)
        victory.place_locked_item(
            PokeRogueItem("Victory", ItemClassification.progression, None, self.player)
        )
        victory_region.locations.append(victory)

    def _has_species(self, state, count: int) -> bool:
        needed = min(count, len(self.species_pool))
        return state.has_group("Species Unlocks", self.player, needed)

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
        for species in self.species_pool:
            if species.species_id in precollected:
                continue
            pool.append(self.create_item(species_item_name(species.display)))

        total_locations = len(self.multiworld.get_unfilled_locations(self.player))
        remaining = total_locations - len(pool)

        if remaining < 0:
            # Should be impossible given generate_early's clamping, but never
            # ship a world that can crash the fill on an edge case.
            logger.warning(
                "PokeRogue (%s): trimmed %d species unlocks that did not fit.",
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
        return {
            "goal_wave": self.goal_wave,
            "wave_check_interval": self.options.wave_check_interval.value,
            "dexsanity": bool(self.options.dexsanity),
            "death_link": bool(self.options.death_link),
            "game_version": SOURCE_GAME_VERSION,
            # numeric SpeciesId -> AP location id, for catch events
            "dexsanity_species": (
                {
                    str(s.species_id): LOCATION_NAME_TO_ID[dexsanity_location_name(s.display)]
                    for s in self.species_pool
                }
                if self.options.dexsanity
                else {}
            ),
            # AP item id -> numeric SpeciesId, for unlock grants
            "species_items": {
                str(ITEM_NAME_TO_ID[species_item_name(s.display)]): s.species_id
                for s in STARTER_SPECIES
            },
            # Every species that can ever be unlocked this seed. Anything absent
            # is permanently locked and the bridge greys it out.
            "pool_species": [s.species_id for s in self.species_pool],
            "starting_species": [s.species_id for s in self.starting_species],
            "wave_locations": {
                str(w.wave): w.address for w in self.wave_locations
            },
        }
