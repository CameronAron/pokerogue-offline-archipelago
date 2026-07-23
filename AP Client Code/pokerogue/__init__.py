"""PokeRogue -- Archipelago world definition.

Targets the standalone offline desktop build of PokeRogue (Electron), patched
with the Archipelago bridge shipped alongside this apworld. See docs/setup_en.md.
"""

import logging
from typing import Any, ClassVar

from BaseClasses import Item, ItemClassification, LocationProgressType, Region, Tutorial
from Options import OptionGroup
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch_subprocess

from .Items import (
    EXP_GAIN_TIERS,
    FILLER_ITEMS,
    ITEM_CLASSIFICATION,
    ITEM_GROUPS,
    ITEM_NAME_TO_ID,
    PROGRESSIVE_EXP_GAIN_ITEM,
    PURE_FILLER_NAMES,
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
from .Options import (
    Dexsanity,
    DexsanityEncounterBias,
    DexsanityExcludeAboveCost,
    DisableLevelCap,
    PokeRogueOptions,
    ProgressiveExpGain,
    RandomStarters,
    SplitDexsanityRewards,
    StartingSpecies,
)
from .Species import (
    DEFAULT_STARTER_POOL,
    DEXSANITY_RARE_ENCOUNTER_ONLY,
    DEXSANITY_UNOBTAINABLE,
    SOURCE_GAME_VERSION,
    STARTER_SPECIES,
    SpeciesInfo,
)

logger = logging.getLogger("PokeRogue")

MENU = "Menu"

#: Vanilla's own cap on combined starter cost for a single team (see
#: https://wiki.pokerogue.net/gameplay:modes:classic). Applied to whichever
#: starter pool is in play -- curated or full-catalog random -- so starting
#: species always respect the same budget a real starter-select screen would.
STARTER_COST_CAP = 10

#: How much of the full species catalog to draw starting species from when
#: Random Starters is on, weighted toward lower cost so an opening run is
#: actually playable. Not player-facing -- just keeps a fresh game from
#: handing out three cost-10 legendaries as your only options.
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
    option_groups = [
        OptionGroup(
            "Sanities",
            [
                Dexsanity,
                DexsanityExcludeAboveCost,
                DexsanityEncounterBias,
                SplitDexsanityRewards,
                ProgressiveExpGain,
                DisableLevelCap,
            ],
        ),
        OptionGroup("Starters", [RandomStarters, StartingSpecies]),
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
        #: Starting species (curated mode only) that skip their own
        #: dexsanity location, since vanilla already considers them caught.
        self.precredited_species: set[int] = set()
        #: How many dexsanity locations got LocationProgressType.EXCLUDED.
        #: create_items uses this to guarantee enough pure-filler items exist
        #: to cover them -- an excluded location can only ever hold a plain
        #: filler item, and the normal weighted filler roll can land on
        #: useful-classified entries (Master Ball etc.) that don't qualify.
        self.excluded_location_count: int = 0
        self.wave_locations: list = []
        self.goal_wave: int = 200

    # ------------------------------------------------------------------ setup

    def generate_early(self) -> None:
        opts = self.options
        self.goal_wave = opts.goal_wave.wave
        interval = opts.wave_check_interval.value
        self.wave_locations = build_wave_locations(interval, self.goal_wave)

        requested_starting = min(opts.starting_species.value, len(STARTER_SPECIES))

        # Dexsanity on: every species is in play, full stop -- no pool size to
        # tune, since every species brings its own location with it.
        #
        # Dexsanity off: nothing grows the roster after the start (see
        # create_items), so there is no pool at all beyond the starting
        # species themselves.
        self.species_pool = list(STARTER_SPECIES) if opts.dexsanity else []

        if opts.random_starters:
            self.starting_species = self._pick_random_starting_species(requested_starting)
        else:
            self.starting_species = self._pick_curated_starting_species(requested_starting)
            # Vanilla already considers these caught from the moment a fresh
            # save exists -- don't ask the player to re-catch their own
            # starting species just to satisfy a check.
            self.precredited_species = {s.species_id for s in self.starting_species}

        for species in self.starting_species:
            self.multiworld.push_precollected(
                self.create_item(species_item_name(species.display))
            )

    def _pick_random_starting_species(self, count: int) -> list[SpeciesInfo]:
        """Sample starting species from the full catalog under the vanilla cost cap.

        Candidates are pre-filtered to a low-cost-biased window before the
        cap is applied, so a fresh run isn't stuck picking between three
        cost-10 legendaries -- see STARTING_SPECIES_CANDIDATE_MULTIPLIER.
        """
        candidates = sorted(STARTER_SPECIES, key=lambda s: s.cost)
        window = max(count * STARTING_SPECIES_CANDIDATE_MULTIPLIER, STARTING_SPECIES_CANDIDATE_MINIMUM)
        candidates = candidates[:window] if len(candidates) >= window else candidates
        return self._pick_cost_capped(candidates, count, "Random Starters")

    def _pick_curated_starting_species(self, count: int) -> list[SpeciesInfo]:
        """Sample from the 27-species curated pool under the vanilla cost cap."""
        return self._pick_cost_capped(list(DEFAULT_STARTER_POOL), count, "the curated starter pool")

    def _pick_cost_capped(
        self, candidates: list[SpeciesInfo], count: int, pool_description: str
    ) -> list[SpeciesInfo]:
        """Greedily accept species from a shuffled candidate list while the
        combined cost still fits the vanilla 10-point starter budget --
        applied to both starter modes for consistency with what a real
        starter-select screen would ever let you bring into a run. If the
        requested count cannot be reached within budget (e.g. every curated
        species costs 3+, so 4 of them already exceeds a cost-10 cap),
        returns as many as fit and warns rather than exceeding the budget.
        """
        rng = self.random
        shuffled = list(candidates)
        rng.shuffle(shuffled)

        chosen: list[SpeciesInfo] = []
        total_cost = 0
        for species in shuffled:
            if len(chosen) >= count:
                break
            if total_cost + species.cost > STARTER_COST_CAP:
                continue
            chosen.append(species)
            total_cost += species.cost

        if len(chosen) < count:
            logger.warning(
                "PokeRogue (%s): %s can't fit %d species under the %d-point cost "
                "cap -- only %d fit (total cost %d).",
                self.player_name,
                pool_description,
                count,
                STARTER_COST_CAP,
                len(chosen),
                total_cost,
            )
        return chosen

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
            exclude_above = self.options.dexsanity_exclude_above_cost.value
            for species in self.species_pool:
                if species.species_id in self.precredited_species:
                    continue
                if species.enum_name in DEXSANITY_UNOBTAINABLE:
                    # No wild spawn anywhere, and confirmed excluded from the
                    # one encounter that could otherwise substitute for one --
                    # a check requiring a genuine catch of this species could
                    # never be completed by ordinary play, so it doesn't get
                    # a location at all. See Species.py's own docstring for
                    # exactly what was checked.
                    continue
                name = dexsanity_location_name(species.display)
                loc = PokeRogueLocation(self.player, name, LOCATION_NAME_TO_ID[name], menu)
                if species.cost > exclude_above or species.enum_name in DEXSANITY_RARE_ENCOUNTER_ONLY:
                    # Still a real, checkable location -- just protected from
                    # ever holding something another location needs, so a
                    # rare or hard-to-reach species can't gate someone else's
                    # progress. See dexsanity_exclude_above_cost's docstring.
                    # Rare-encounter-only species are always excluded here
                    # regardless of the cost threshold -- they have no normal
                    # wild spawn at any cost, only a rare, non-guaranteed
                    # encounter, which the cost slider has no way to see.
                    loc.progress_type = LocationProgressType.EXCLUDED
                    self.excluded_location_count += 1
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
        precollected = {s.species_id for s in self.starting_species}

        # (cost, item) so overflow trimming below can shed the costliest
        # species first -- the same ones already being treated as unreliable
        # by dexsanity_exclude_above_cost.
        species_items: list[tuple[int, Item]] = []
        if self.options.dexsanity:
            for species in self.species_pool:
                if species.species_id in precollected:
                    continue
                species_items.append(
                    (species.cost, self.create_item(species_item_name(species.display)))
                )

        exp_gain_items: list[Item] = []
        if self.options.progressive_exp_gain:
            exp_gain_items = [
                self.create_item(PROGRESSIVE_EXP_GAIN_ITEM) for _ in self.wave_locations
            ]

        total_locations = len(self.multiworld.get_unfilled_locations(self.player))

        # Excluded locations can only ever hold a plain filler item, so at
        # most (total_locations - excluded_location_count) slots are
        # available for species/EXP-gain items combined. Dexsanity and
        # Progressive EXP Gain are independent toggles and can both demand a
        # large item count at once, so this can't just be assumed to fit --
        # it has to be checked and, if needed, trimmed.
        max_non_fillable = total_locations - self.excluded_location_count
        non_fillable_count = len(species_items) + len(exp_gain_items)

        if non_fillable_count > max_non_fillable:
            overflow = non_fillable_count - max_non_fillable
            species_items.sort(key=lambda pair: pair[0])  # cheapest first
            trimmed = 0
            while overflow > 0 and species_items:
                species_items.pop()  # drop the costliest remaining
                overflow -= 1
                trimmed += 1
            if overflow > 0:
                # Species alone couldn't cover it -- would need
                # excluded_location_count to approach the whole species pool,
                # essentially impossible, but degrade safely regardless.
                exp_gain_items = exp_gain_items[: max(0, len(exp_gain_items) - overflow)]
            if trimmed:
                logger.warning(
                    "PokeRogue (%s): %d high-cost species lost their unlock item so "
                    "%d excluded locations could still get a guaranteed pure-filler "
                    "item. Raise dexsanity_exclude_above_cost, or turn off Progressive "
                    "EXP Gain, to avoid this.",
                    self.player_name,
                    trimmed,
                    self.excluded_location_count,
                )

        pool: list[Item] = [item for _, item in species_items]
        pool.extend(exp_gain_items)

        remaining = total_locations - len(pool)

        # Excluded locations can only ever hold a plain filler item, so the
        # first slice of filler generated is guaranteed pure filler -- enough
        # to cover every excluded location regardless of what the weighted
        # roll below would otherwise have picked. The overflow handling above
        # guarantees remaining >= excluded_location_count here.
        guaranteed_pure = min(remaining, self.excluded_location_count)
        for _ in range(guaranteed_pure):
            pool.append(self.create_item(self.random.choice(PURE_FILLER_NAMES)))
        for _ in range(remaining - guaranteed_pure):
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
        exp_gain_on = bool(self.options.progressive_exp_gain)
        return {
            "goal_wave": self.goal_wave,
            "wave_check_interval": self.options.wave_check_interval.value,
            "dexsanity": dexsanity_on,
            "dexsanity_encounter_bias": self.options.dexsanity_encounter_bias.value,
            "progressive_exp_gain": exp_gain_on,
            "death_link": bool(self.options.death_link),
            "game_version": SOURCE_GAME_VERSION,
            # numeric SpeciesId -> AP location id, for catch events. Excludes
            # precredited curated starters, which never get a location at all.
            "dexsanity_species": (
                {
                    str(s.species_id): LOCATION_NAME_TO_ID[dexsanity_location_name(s.display)]
                    for s in self.species_pool
                    if s.species_id not in self.precredited_species
                    and s.enum_name not in DEXSANITY_UNOBTAINABLE
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
            # from this list is left fully alone (not a starter at all). Only
            # meaningful when dexsanity is on -- see the gate's own docs.
            "all_starter_species": [s.species_id for s in STARTER_SPECIES],
            "pool_species": [s.species_id for s in self.species_pool],
            "starting_species": [s.species_id for s in self.starting_species],
            "wave_locations": {str(w.wave): w.address for w in self.wave_locations},
            # Progressive EXP Gain: item id to count copies of, and the rate
            # table to look the count up against. Both None/empty when the
            # option is off.
            "progressive_exp_gain_item": (
                ITEM_NAME_TO_ID[PROGRESSIVE_EXP_GAIN_ITEM] if exp_gain_on else None
            ),
            "exp_gain_tiers": list(EXP_GAIN_TIERS) if exp_gain_on else [],
            "disable_level_cap": bool(self.options.disable_level_cap),
        }
