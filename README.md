# PokeRogue Archipelago

A standalone, offline desktop build of [PokéRogue](https://pokerogue.net/) with Archipelago multiworld support built in.

This started as a fork of [PokéRogue Offline](https://github.com/PokeRogue-Offline/pokerogue-offline), which packages PokéRogue as a native Windows, macOS, and Linux app. This project adds an Archipelago client on top, so a Classic mode run can send and receive checks alongside any other game in your multiworld.

## Getting started

Grab the latest release from the [Releases page](../../releases). It includes the game and the apworld together, so there's nothing to build or clone.

1. Copy `pokerogue.apworld` into your Archipelago install's `custom_worlds` folder and restart the Launcher.
2. Generate a seed.
3. Start **PokeRogue Client** from the Archipelago Launcher, then run the game from wherever you unzipped it. It connects on its own.

The full [setup guide](AP%20Client%20Code/pokerogue/docs/setup_en.md) covers the rest, including troubleshooting and client commands.

## What Archipelago support adds

**Dexsanity.** Every species starts locked. Catching one for the first time sends a check, and the matching item is what lets you actually field it — including a wild catch mid-run, which won't join your party without it.

**Wave milestones.** A check every N waves of Classic mode, up to a configurable goal (200 by default, the real ending).

**Progressive EXP Gain.** An alternative to species-hunting: wave checks raise your experience gain rate instead, starting reduced and climbing past normal with the full set. It's a rate, not a hard cap, so a run can never become unwinnable just because the multiworld hasn't sent enough copies yet.

**Disable Level Cap.** A separate option that removes Classic mode's normal level ceiling entirely — independent of Progressive EXP Gain, since one controls how fast experience comes in and the other controls how high it's allowed to go.

**Dexsanity Encounter Bias.** An optional chance to nudge a wild or boss encounter toward a species you still need, without ever touching the game's own random number sequence — the substitution only happens after the game's natural roll has already fully resolved.

**Curated or random starters.** Start with a random selection from the whole roster, or the same 27 species (three per generation) a fresh PokéRogue account starts with, both under the same 10-point cost budget the game's own starter screen enforces.

## Credits

Built on [PokéRogue](https://github.com/pagefaultgames/pokerogue) and [PokéRogue Offline](https://github.com/PokeRogue-Offline/pokerogue-offline). Not affiliated with Nintendo, The Pokémon Company, or the official PokéRogue team.
