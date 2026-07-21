# PokeRogue

## Where is the options page?

The [player options page](../player-options) has all the options you need to
configure and export a config file.

## What does randomization do to this game?

Two things change.

**You have to earn the right to use each Pokemon.** Normally PokeRogue lets you
pick any starter you have caught. Here, every species in the seed's pool starts
locked, and stays locked until the matching unlock item is sent to you from the
multiworld. The starter select screen refuses any species you have not been
granted. You begin with a small number of species (three by default) so you can
actually start a run.

Species that are *not* in the seed's pool can never be unlocked at all. The pool
size is therefore your entire roster for the whole game, and picking a small
pool makes for a much more constrained run than vanilla PokeRogue.

**Progress and catching send checks.** Clearing wave milestones in Classic mode
sends checks, and (with Dexsanity on) so does catching each pooled species for
the first time.

Nothing else about the game is randomized. Biomes, encounters, movesets, the
shop, and the item pool inside a run all behave exactly as they normally do.

## What is the goal?

Beat Classic mode: clear wave 200 by defeating Eternamax Eternatus.

Shorter goals (wave 50, 100, 150) are available for testing or for async games
that need to fit in less time. With a shorter goal you complete as soon as you
*reach* that wave, rather than having to kill a final boss.

## What items and locations get shuffled?

**Locations** are:

- **Wave milestones** -- one check every N waves of Classic mode (10 by
  default), up to but not including your goal wave.
- **Dexsanity** (optional, on by default) -- one check for the first time you
  catch each species in the pool. Catching an evolved form counts for its whole
  line, so catching a Venusaur credits Bulbasaur.

**Items** are:

- **Species unlocks** -- one per species in the pool. These are the progression
  items.
- **Filler** -- Rare Candies, ball packs, money, egg vouchers, Exp Charms and
  similar. These are cosmetic placeholders in the current version; see the
  caveat below.

## Which items can be in another player's world?

Any of them. Species unlocks and filler both shuffle freely into the multiworld.

## What does another world's item look like in PokeRogue?

There is no in-game item model, so items are not represented on the field.
Received items are reported by the PokeRogue client, and species unlocks take
effect immediately -- the newly unlocked species becomes selectable in starter
select the next time you open it.

## When the player receives an item, what happens?

Species unlocks are applied by the client and take effect immediately.

**Filler items are currently placeholders.** They are named after real PokeRogue
consumables and they occupy item-pool slots correctly, but the current version
of the bridge does not inject them into a running save. They are logged by the
client and nothing more. Treat them as junk in the AP sense -- they exist so
that the item and location counts balance, which is what the multiworld needs.

## Unique local commands

The PokeRogue client supports these in addition to the standard ones:

- `/bridge` -- show whether the game is connected, and whether a PokeRogue
  process is running at all.
- `/unlocked` -- list every species you have been granted so far.
- `/resync` -- force a full state push to the game.

## Known limitations

- Only **Classic** mode counts. Endless, Daily and Challenge runs are ignored;
  they will not send wave checks and cannot complete the goal.
- The DeathLink implementation is one-directional in practice: losing a run
  sends a death, but receiving one only shows a message. PokeRogue has no safe
  way to end a run from outside without risking save corruption.
- Species data is generated from a specific game version. If your game is much
  newer than the apworld, newly added species will simply be absent from the
  pool rather than causing an error.
