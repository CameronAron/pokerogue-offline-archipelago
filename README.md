# PokeRogue Archipelago

A standalone, offline desktop build of [PokéRogue](https://pokerogue.net/)
with built-in support for [Archipelago](https://archipelago.gg) multiworld
randomizers.

This is a fork of [PokéRogue Offline](https://github.com/PokeRogue-Offline/pokerogue-offline),
which itself packages the official PokéRogue game as a native Windows,
macOS, and Linux application. This fork adds an Archipelago client bridge on
top, letting a Classic mode run send and receive checks alongside any other
game in a multiworld.

## What Archipelago support adds

- **Dexsanity** -- catching each species for the first time sends a check,
  and the matching item is what lets you actually field it. Every species
  starts locked.
- **Wave milestones** -- Classic mode sends a check every N waves, up to a
  configurable goal wave (default 200, the true ending).
- **Progressive Level Cap** -- an alternative to Dexsanity's species-hunting:
  wave checks instead raise your Classic-mode level cap in the same 20-tier
  progression the base game's own automatic cap uses.
- **Curated or random starters** -- start with a random selection from every
  species in the game, or the same 27 species (three per generation) a real
  fresh PokéRogue account starts with, under the same 10-point cost budget
  the game's own starter-select screen enforces.

Full setup instructions, including how to build the patched game and connect
it to a multiworld, are in the
[setup guide](AP%20Client%20Code/pokerogue/docs/setup_en.md).

## Getting started

1. Install [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases).
2. Drop `pokerogue.apworld` from `releases` into Archipelago's
   `custom_worlds` folder.
3. Follow the [setup guide](AP%20Client%20Code/pokerogue/docs/setup_en.md) to
   generate a seed and connect.


## Credits

Built on [PokéRogue](https://github.com/pagefaultgames/pokerogue) and
[PokéRogue Offline](https://github.com/PokeRogue-Offline/pokerogue-offline).
Not affiliated with Nintendo, The Pokémon Company, or the official PokéRogue
team.
