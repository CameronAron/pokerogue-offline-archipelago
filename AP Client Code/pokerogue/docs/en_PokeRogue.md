# PokeRogue

## Where is the options page?

The [player options page](../player-options) has all the options you need to
configure and export a config file.

## What does randomization do to this game?

Two things change.

**You have to earn the right to use each Pokemon.** Every species starts
locked. The starter select screen refuses any species you have not been
granted, exactly the way it already refuses any species you have never
caught -- unlocking a species is what makes the game consider it caught. You
begin with a small number of species (three by default) so you can actually
start a run.

**Progress sends checks.** How this works depends on whether Dexsanity is on.

## The two modes

### Dexsanity on (default)

Every species in the game is in play. Catching a species for the first time in
a run sends a check, and receiving that species' unlock item is what lets you
actually use it -- catching and unlocking are separate: catching sends the
check, the item is what the multiworld sends back to let you field it. Wave
milestones (every 10 waves of Classic by default) send additional checks.

### Dexsanity off

Your roster is fixed to your starting species for the whole game -- nothing
else can ever be unlocked, since there's no dexsanity pool to draw more
species items from. Wave milestones still send checks, but instead of species
unlocks, each one sends a **Progressive Level Cap** item.

Progressive Level Cap mirrors PokeRogue's own vanilla level cap system, which
normally raises automatically every 10 waves. In this mode, each copy you
receive raises your cap by one tier instead, following the same 20-tier table
the base game uses (level 10 at the start, up to level 200 for the wave 200
final boss). **Rare Candies still bypass the cap entirely**, exactly like in
vanilla -- Progressive Level Cap only affects normal experience-based leveling.

This mode plays very differently: no Pokemon-collecting meta, just your
starting team and a pacing challenge.

## What is the goal?

Beat Classic mode: clear wave 200 by defeating Eternamax Eternatus.

Shorter goals (wave 50, 100, 150) are available for testing or for async games
that need to fit in less time. With a shorter goal you complete as soon as you
*reach* that wave, rather than having to kill a final boss.

## What items and locations get shuffled?

**Locations** are:

- **Wave milestones** -- one check every N waves of Classic mode (10 by
  default), up to but not including your goal wave.
- **Dexsanity** (Dexsanity mode only) -- one check for the first time you
  catch each species. Catching an evolved form counts for its whole line, so
  catching a Venusaur credits Bulbasaur.

**Items** are:

- **Species unlocks** (Dexsanity mode only) -- one per species in the game.
  These are the progression items.
- **Progressive Level Cap** (non-Dexsanity mode only) -- one copy per wave
  milestone. Also progression.
- **Filler** -- Rare Candies, ball packs, money, egg vouchers, Exp Charms and
  similar, used to pad out Dexsanity mode's item pool. Currently placeholders;
  see the caveat below.

## Which items can be in another player's world?

Any of them. Species unlocks, Progressive Level Cap, and filler all shuffle
freely into the multiworld.

## What does another world's item look like in PokeRogue?

There is no in-game item model, so items are not represented on the field.
Received items are reported by the PokeRogue client and take effect
immediately: a newly unlocked species becomes selectable in starter select
right away, and a new Progressive Level Cap copy raises your cap on your next
level-up check.

## When the player receives an item, what happens?

Species unlocks and Progressive Level Cap both apply immediately.

**Filler items are currently placeholders.** They are named after real
PokeRogue consumables and they occupy item-pool slots correctly, but the
current version of the bridge does not inject them into a running save. They
are logged by the client and nothing more.

## Unique local commands

The PokeRogue client supports these in addition to the standard ones:

- `/bridge` -- show whether the game is connected, and whether a PokeRogue
  process is running at all.
- `/unlocked` -- list every species you have been granted so far.
- `/levelcap` -- show your current level cap tier (non-Dexsanity mode).
- `/resync` -- force a full state push to the game.

## Known limitations

- Only **Classic** mode counts. Endless, Daily and Challenge runs are ignored.
- DeathLink is one-directional in practice: losing a run sends a death, but
  receiving one only shows a message. PokeRogue has no safe way to end a run
  from outside without risking save corruption.
- Species data is generated from a specific game version. If your game is much
  newer than the apworld, newly added species will simply be absent from the
  pool rather than causing an error.
