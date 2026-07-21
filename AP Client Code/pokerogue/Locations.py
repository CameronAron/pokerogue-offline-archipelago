"""Location definitions for the PokeRogue apworld.

ID layout (location namespace, independent of the item namespace):
    BASE + <species_id>        dexsanity "first catch" checks
    BASE + 90000 + <wave>      Classic-mode wave milestones
"""

from typing import NamedTuple

from BaseClasses import Location

from .Species import STARTER_SPECIES

BASE_ID = 77_770_000
WAVE_OFFSET = 90_000

#: Highest wave Classic mode can reach.
MAX_WAVE = 200


class PokeRogueLocation(Location):
    game = "PokeRogue"


class WaveLocation(NamedTuple):
    name: str
    address: int
    wave: int


def dexsanity_location_name(display: str) -> str:
    return f"Catch {display}"


def wave_location_name(wave: int) -> str:
    return f"Wave {wave} Cleared"


#: Every possible dexsanity location, keyed by name. Only the subset matching
#: the rolled species pool is actually registered for a given seed.
DEXSANITY_LOCATIONS: dict[str, int] = {
    dexsanity_location_name(s.display): BASE_ID + s.species_id for s in STARTER_SPECIES
}

#: location name -> numeric SpeciesId, used by the client to resolve a catch
#: event into a location to send.
LOCATION_NAME_TO_SPECIES_ID: dict[str, int] = {
    dexsanity_location_name(s.display): s.species_id for s in STARTER_SPECIES
}


def build_wave_locations(interval: int, goal_wave: int) -> list[WaveLocation]:
    """Return the wave milestone locations for the given interval and goal.

    The goal wave itself is *not* a location -- it is the completion event.
    """
    waves = [w for w in range(interval, goal_wave + 1, interval) if w < goal_wave]
    return [WaveLocation(wave_location_name(w), BASE_ID + WAVE_OFFSET + w, w) for w in waves]


#: Every wave milestone that any legal option combination could produce, so the
#: static location_name_to_id table covers all of them.
ALL_WAVE_LOCATIONS: dict[str, int] = {
    wave_location_name(w): BASE_ID + WAVE_OFFSET + w for w in range(1, MAX_WAVE + 1)
}

#: The full location_name_to_id table exposed to Archipelago.
LOCATION_NAME_TO_ID: dict[str, int] = {**DEXSANITY_LOCATIONS, **ALL_WAVE_LOCATIONS}

LOCATION_GROUPS: dict[str, set[str]] = {
    "Dexsanity": set(DEXSANITY_LOCATIONS),
    "Wave Milestones": set(ALL_WAVE_LOCATIONS),
}

for _gen in range(1, 10):
    LOCATION_GROUPS[f"Generation {_gen} Dexsanity"] = {
        dexsanity_location_name(s.display) for s in STARTER_SPECIES if s.generation == _gen
    }
