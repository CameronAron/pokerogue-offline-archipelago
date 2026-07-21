# PokeRogue

## Where is the options page?

The [player options page](../player-options) has all the options you need to
configure and export a config file. Options are grouped into **Sanities**
(Dexsanity, its cost exclusion, Progressive Level Cap) and **Starters**
(random vs. curated, how many).

## What does randomization do to this game?

**You have to earn the right to use each Pokemon -- but only when Dexsanity
is on.** With it on, every species starts locked; the starter select screen
refuses any species you haven't been granted, the same way it already
refuses any species you've never caught. Catching something during a run
still works, but it won't join your party until its unlock item arrives.
With Dexsanity off, none of this applies -- you catch and use Pokemon exactly
like vanilla PokeRogue.

**Progress sends checks.** Wave milestones (every 10 waves of Classic mode by
default) always send checks. Catching a species for the first time also
sends one, but only when Dexsanity is on.

## The two independent Sanities

**Dexsanity** and **Progressive Level Cap** are separate toggles -- turn on
either, both, or neither.

- **Dexsanity on**: every species is in play. Catching one for the first time
  sends a check; the matching item lets you field it.
- **Dexsanity off**: your roster grows through normal catching, exactly like
  vanilla. No species checks exist.
- **Progressive Level Cap on**: every wave-milestone check instead sends a
  copy of a Progressive Level Cap item. Each copy raises your Classic-mode
  level cap by one tier, following the same 20-tier table (level 10 through
  level 200) the base game's own automatic cap uses. **Rare Candy still
  bypasses the cap entirely**, exactly like vanilla -- it never goes through
  the capped code path in the first place.
- **Progressive Level Cap off**: wave checks send ordinary filler (or, with
  Dexsanity also on, they're separate from the species pool entirely).

### Protecting rare species from gating other players

**Dexsanity Exclude Above Cost** (default 8) keeps species above that starter
cost -- the legendaries and rarest mons -- from ever holding an item that
matters somewhere else. Their dexsanity location still exists and can hold an
ordinary filler item, it just can't be the location standing between someone
and something they need. Lower it to protect more species, or raise it to 10
to disable the protection entirely.

## Starters

**Random Starters** (on by default) draws your starting species from
everything in the game. Turn it off to draw from the same 27 species (three
per generation) a real fresh PokeRogue account starts with, under the same
10-point combined cost cap the game's own starter-select screen enforces.
Curated starters also skip their own dexsanity check, since vanilla already
counts them as caught from the moment the save exists.

**Starting Species** controls how many you begin with. In curated mode this
is capped by the 10-point budget -- every curated species costs 3 or 4, so 4+
species is mathematically impossible under that budget, and you'll get as
many as fit with a warning at generation.

## What is the goal?

Beat Classic mode: clear wave 200 by defeating Eternamax Eternatus. Shorter
goals (wave 50, 100, 150) are available for testing or async games; with a
shorter goal you complete as soon as you've cleared that wave.

## Which items can be in another player's world?

Any of them -- species unlocks, Progressive Level Cap copies, and filler all
shuffle freely into the multiworld, subject to the exclusion protection above.

## What does another world's item look like in PokeRogue?

There's no in-game item model, so items aren't represented on the field.
Received items are reported by the PokeRogue client and take effect
immediately.

## When the player receives an item, what happens?

Species unlocks and Progressive Level Cap both apply immediately. **Filler
items are currently placeholders** -- they occupy pool slots correctly and
balance the item count, but the bridge doesn't inject them into a running
save yet.

## Unique local commands

- `/bridge` -- whether the game is connected, and whether a PokeRogue process
  is running at all.
- `/unlocked` -- species you've been granted so far.
- `/pending` -- species with a dexsanity check you haven't caught yet.
- `/levelcap` -- your current Classic-mode level cap tier.
- `/resync` -- force a full state push to the game.

## Known limitations

- Only **Classic** mode counts. Endless, Daily and Challenge runs are ignored.
- DeathLink is one-directional in practice: losing a run sends a death, but
  receiving one only shows a message. PokeRogue has no safe way to end a run
  from outside without risking save corruption.
- Wild encounter species are not biased toward what you still need to catch.
  PokeRogue's encounters are drawn from a single seeded RNG stream shared
  with every other random event in a run, and safely nudging that stream
  from outside isn't something that can be verified without extensive
  play-testing this project hasn't done. `dexsanity_exclude_above_cost`
  protects other players from being gated by a rare species; it doesn't make
  that species spawn more often.
