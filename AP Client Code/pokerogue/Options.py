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


class Dexsanity(DefaultOnToggle):
    """Adds a check for catching each species, and sends every species as an item.

    Turning this off replaces species-hunting with Progressive Level Cap items
    instead: your roster stays fixed at your starting species, and each wave
    check raises your Classic-mode level cap by one tier.
    """

    display_name = "Dexsanity"


class StartingSpecies(Range):
    """How many species you start the game with unlocked."""

    display_name = "Starting Species"
    range_start = 1
    range_end = 6
    default = 3


class WaveCheckInterval(Range):
    """Sends a check every this many waves of Classic mode, up to your goal wave."""

    display_name = "Wave Check Interval"
    range_start = 5
    range_end = 25
    default = 10


class SplitDexsanityRewards(Toggle):
    """Fills dexsanity checks with useful items instead of ordinary filler.

    Has no effect when Dexsanity is off.
    """

    display_name = "Useful Dexsanity Rewards"


@dataclass
class PokeRogueOptions(PerGameCommonOptions):
    goal_wave: GoalWave
    dexsanity: Dexsanity
    starting_species: StartingSpecies
    wave_check_interval: WaveCheckInterval
    split_dexsanity_rewards: SplitDexsanityRewards
    death_link: DeathLink
    start_inventory_from_pool: StartInventoryPool
