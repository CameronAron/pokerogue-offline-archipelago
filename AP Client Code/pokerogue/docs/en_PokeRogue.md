# PokeRogue

## Where is the options page?

The [player options page](../player-options) has all the options you need to
configure and export a config file. Options are grouped into **Sanities**
(Dexsanity, its cost exclusion, Encounter Bias, Progressive EXP Gain) and
**Starters** (random vs. curated, how many).

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

## The independent Sanities

**Dexsanity** and **Progressive EXP Gain** are separate toggles -- turn on
either, both, or neither. **Dexsanity Encounter Bias** is a separate dial
that only does anything while Dexsanity is on.

- **Dexsanity on**: every species is in play. Catching one for the first time
  sends a check; the matching item lets you field it.
- **Dexsanity off**: your roster grows through normal catching, exactly like
  vanilla. No species checks exist.
- **Progressive EXP Gain on**: every wave-milestone check instead sends a
  copy of a Progressive EXP Gain item. Without any copies, experience gained
  is reduced to a fraction of normal -- still winnable through skill and
  grinding, never a hard wall. Each copy raises your gain rate, climbing back
  to and eventually above normal with the full set. This stacks with Exp
  Charms and other vanilla EXP boosters rather than replacing them -- those
  apply first, and this rate multiplies on top, so a charm you've earned is
  never wasted. **Rare Candy is unaffected either way**, exactly like
  vanilla -- it increments a Pokemon's level directly and was never gated by
  experience gain in the first place.
- **Progressive EXP Gain off**: wave checks send ordinary filler (or, with
  Dexsanity also on, they're separate from the species pool entirely).
- **Dexsanity Encounter Bias** (0-100, off by default): the chance that an
  eligible wild or boss encounter gets swapped for a species you still need
  to catch, instead of whatever the game would have spawned. The swap only
  ever happens within the same rarity tier the original roll landed in, so
  it can never make an encounter easier or harder than the wave already
  intends -- only more likely to be useful. It fades out on its own as you
  complete more of the dex, since there's less left to swap toward, and it
  never affects anything else about how the encounter is generated (shiny
  odds, nature, IVs are untouched).

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
per generation) a real fresh PokeRogue account starts with. Both modes
respect the same 10-point combined starter cost cap the game's own
starter-select screen enforces -- curated starters also skip their own
dexsanity check, since vanilla already counts them as caught from the moment
the save exists.

**Starting Species** controls how many you begin with. Since every curated
species costs 3 or 4, requesting more than 3 in curated mode is impossible
under the 10-point budget -- you'll get as many as fit with a warning at
generation. The same cap applies in random mode too.

## What is the goal?

Beat Classic mode: clear wave 200 by defeating Eternamax Eternatus. Shorter
goals (wave 50, 100, 150) are available for testing or async games; with a
shorter goal you complete as soon as you've cleared that wave.

## Which items can be in another player's world?

Any of them -- species unlocks, Progressive EXP Gain copies, and filler all
shuffle freely into the multiworld, subject to the exclusion protection above.

## What does another world's item look like in PokeRogue?

There's no in-game item model, so items aren't represented on the field.
Received items are reported by the PokeRogue client and take effect
immediately.

## When the player receives an item, what happens?

Species unlocks and Progressive EXP Gain both apply immediately. **Filler
items are currently placeholders** -- they occupy pool slots correctly and
balance the item count, but the bridge doesn't inject them into a running
save yet.

## Unique local commands

- `/bridge` -- whether the game is connected, and whether a PokeRogue process
  is running at all.
- `/unlocked` -- species you've been granted so far.
- `/pending` -- species with a dexsanity check you haven't caught yet.
- `/expgain` -- your current Progressive EXP Gain rate.
- `/resync` -- force a full state push to the game.

## Known limitations

- Only **Classic** mode counts. Endless, Daily and Challenge runs are ignored.
- DeathLink is one-directional in practice: losing a run sends a death, but
  receiving one only shows a message. PokeRogue has no safe way to end a run
  from outside without risking save corruption.
- Encounter Bias substitutes within the same rarity tier only, and skips any
  encounter it can't confidently match a tier for rather than guess -- so it
  helps often, not always. It's also a probability, not a guarantee: setting
  it to 100 makes every eligible encounter attempt a swap, but "eligible"
  still requires a same-tier species you actually still need.
