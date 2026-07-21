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

from .Species import STARTER_SPECIES

MAX_SPECIES = len(STARTER_SPECIES)


class GoalWave(Choice):
    """The Classic-mode wave you must clear to finish your run.

    200 is a full Classic victory (defeating Eternamax Eternatus) and is the
    intended goal. The shorter values exist for testing and for shorter async
    games -- they complete the goal as soon as you *reach* that wave rather
    than requiring the wave 200 boss kill.
    """

    display_name = "Goal Wave"
    option_wave_50 = 50
    option_wave_100 = 100
    option_wave_150 = 150
    option_wave_200 = 200
    default = 200

    @property
    def wave(self) -> int:
        return int(self.value)


class Dexsanity(DefaultOnToggle):
    """Send a check the first time you catch each species in the randomized pool.

    With this off, the only locations in your world are the wave milestones,
    which caps how many species unlocks your world can hold (see
    species_pool_size). Leaving it on is strongly recommended.
    """

    display_name = "Dexsanity"


class SpeciesPoolSize(Range):
    """How many species are shuffled into the multiworld as unlock items.

    Every species in this pool starts LOCKED -- you cannot put it on your team
    until its unlock item is sent to you. Species outside the pool are never
    unlockable, so this is effectively the size of your entire available roster
    for the whole game.

    If this is larger than the number of locations your world has, it is
    automatically clamped down and a warning is printed during generation.
    """

    display_name = "Species Pool Size"
    range_start = 6
    range_end = MAX_SPECIES
    default = 120


class StartingSpecies(Range):
    """How many species from the pool you begin with already unlocked.

    You need at least one to start a run at all. These are pre-collected, so
    they never occupy a location.
    """

    display_name = "Starting Species"
    range_start = 1
    range_end = 6
    default = 3


class StarterCostBias(Choice):
    """How the randomized species pool is weighted by starter cost.

    Cheap species (cost 1-3) are the ordinary early-game Pokemon; expensive
    ones (8-10) are legendaries and pseudo-legendaries. 'any' ignores cost
    entirely, 'cheap' biases toward usable low-cost mons, and 'balanced'
    guarantees a usable spread across the cost brackets.
    """

    display_name = "Starter Cost Bias"
    option_any = 0
    option_cheap = 1
    option_balanced = 2
    default = 2


class WaveCheckInterval(Range):
    """Send a check every N waves of Classic mode, up to your goal wave."""

    display_name = "Wave Check Interval"
    range_start = 5
    range_end = 25
    default = 10


class SplitDexsanityRewards(Toggle):
    """Put a guaranteed useful item behind every dexsanity check.

    When off, dexsanity locations are filled by the normal multiworld fill and
    may hold junk. When on, your own contribution to the item pool leans more
    heavily on consumables so the checks feel less empty.
    """

    display_name = "Useful Dexsanity Rewards"


@dataclass
class PokeRogueOptions(PerGameCommonOptions):
    goal_wave: GoalWave
    dexsanity: Dexsanity
    species_pool_size: SpeciesPoolSize
    starting_species: StartingSpecies
    starter_cost_bias: StarterCostBias
    wave_check_interval: WaveCheckInterval
    split_dexsanity_rewards: SplitDexsanityRewards
    death_link: DeathLink
    start_inventory_from_pool: StartInventoryPool
