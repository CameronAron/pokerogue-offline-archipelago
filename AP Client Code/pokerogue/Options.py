"""Player YAML options for the PokeRogue apworld."""

from dataclasses import dataclass

from Options import (
    Choice,
    DeathLink,
    DefaultOnToggle,
    PerGameCommonOptions,
    Range,
    StartInventoryPool,
    Toggle,
)


class GoalWave(Choice):
    """The Classic-mode wave that ends the run."""

    display_name = "Goal Wave"
    option_wave_50 = 50
    option_wave_100 = 100
    option_wave_150 = 150
    option_wave_200 = 200
    default = 200

    @property
    def wave(self) -> int:
        return int(self.value)


class WaveCheckInterval(Range):
    """Sends a check every this many waves of Classic mode, up to your goal wave."""

    display_name = "Wave Check Interval"
    range_start = 5
    range_end = 25
    default = 10


# ------------------------------------------------------------------ Sanities

class Dexsanity(DefaultOnToggle):
    """Adds a check for catching each species, and sends every species as an item.

    Every species starts locked; the matching item is what lets you field it.
    Catching an evolved form also credits every species below it in its
    evolution line.
    """

    display_name = "Dexsanity"


class DexsanityExcludeAboveCost(Range):
    """Species above this starter cost never hold a check required for anything else.

    Their dexsanity location still exists and can hold a useful/filler item,
    it just won't be picked to hold something another location needs. Lowering
    this protects against needing to hunt a specific rare or hard-to-reach
    species (a max-cost legendary, for instance) before anyone can progress.
    Set to 10 to disable this protection entirely.
    """

    display_name = "Dexsanity Exclude Above Cost"
    range_start = 1
    range_end = 10
    default = 8


class SplitDexsanityRewards(Toggle):
    """Fills dexsanity checks with useful items instead of ordinary filler.

    Has no effect when Dexsanity is off.
    """

    display_name = "Useful Dexsanity Rewards"


class ProgressiveLevelCap(Toggle):
    """Sends a Progressive Level Cap item on every wave check instead of a normal reward.

    Each copy raises your Classic-mode level cap by one tier, following the
    same 20-tier table the base game's automatic cap uses. Rare Candy still
    bypasses the cap entirely, same as vanilla. Independent of Dexsanity --
    combine both, either alone, or neither.
    """

    display_name = "Progressive Level Cap"


# ------------------------------------------------------------------ Starters

class RandomStarters(DefaultOnToggle):
    """Draws your starting species from every species in the game.

    Turning this off instead draws from the same 27 species (the first three
    of each generation) that a real fresh PokeRogue account starts with.
    """

    display_name = "Random Starters"


class StartingSpecies(Range):
    """How many species you start the game with unlocked.

    When Random Starters is off, this is capped by the vanilla 10-point
    starter cost budget -- if you ask for more than the curated 27-species
    pool can afford, you'll get as many as fit and a warning during generation.
    """

    display_name = "Starting Species"
    range_start = 1
    range_end = 6
    default = 3


@dataclass
class PokeRogueOptions(PerGameCommonOptions):
    goal_wave: GoalWave
    wave_check_interval: WaveCheckInterval
    dexsanity: Dexsanity
    dexsanity_exclude_above_cost: DexsanityExcludeAboveCost
    split_dexsanity_rewards: SplitDexsanityRewards
    progressive_level_cap: ProgressiveLevelCap
    random_starters: RandomStarters
    starting_species: StartingSpecies
    death_link: DeathLink
    start_inventory_from_pool: StartInventoryPool
