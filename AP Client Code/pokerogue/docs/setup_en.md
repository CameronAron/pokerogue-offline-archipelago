# PokeRogue Setup Guide

## Required software

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.4 or
  newer.
- The `pokerogue.apworld` file from this release.
- A **patched PokeRogue Offline desktop build**. You build this yourself; see
  below. The unpatched official builds will not work.

## How this works

PokeRogue runs as JavaScript inside an Electron window, so there is no game
memory for a client to read the way an emulator client would. Instead the
patched game opens a WebSocket back to the Archipelago client:

```
Archipelago server  <--->  PokeRogue Client  <--->  the game
                              (Python)          (localhost:17777)
```

The client holds the authoritative state. The game is told the full unlock set
every time it changes, so crashing, reloading, or reconnecting mid-run all
recover correctly on their own.

## Installing the apworld

Double-click `pokerogue.apworld`, or copy it into your Archipelago install's
`custom_worlds` folder. Restart the Archipelago Launcher afterwards.

## Building a patched game

The PokeRogue Offline project builds by cloning upstream PokeRogue and applying
a set of patches to it. Archipelago support is one more patch in that pipeline.

1. Clone [pokerogue-offline](https://github.com/PokeRogue-Offline/pokerogue-offline)
   (or your own fork of it).
2. Copy the Archipelago integration files in:
   - `archipelago-bridge.js` into `patches/all/node/`
   - `ap-bridge.ts` into `new-files/src/system/archipelago/`
3. Register the patch by adding this line to `scripts/apply-patches.sh`,
   alongside the other `apply_patch` calls in the "All platforms" block:

   ```bash
   apply_patch "archipelago-bridge.js"   all
   ```

4. Build using the project's normal workflow. For Windows that is
   `.github/workflows/build-exe.yml`, which you can run via GitHub Actions
   (Actions -> Build PokeRogueOffline Windows EXE -> Run workflow), or locally
   by following the same steps.

The patch touches only two existing files (`main.ts` and `game-over-phase.ts`)
plus the new bridge module -- it no longer needs to touch starter select at
all, since the bridge drives the game's own catch data directly instead of
adding a second check next to it. The patch is idempotent and fails loudly: if
upstream PokeRogue has changed enough that an anchor no longer matches, the
build stops with a message naming the anchor rather than silently producing a
broken exe.

### Verifying the patch applied

Launch the built game and open the developer console (`DEBUG=1` env var, or
Ctrl+Shift+I in a dev build). You should see the bridge attempting to connect
to `ws://127.0.0.1:17777` every few seconds.

## Joining a multiworld

1. Start the **PokeRogue Client** from the Archipelago Launcher.
2. Enter the server address and your slot name when prompted.
3. Launch the patched PokeRogue build. It connects automatically.
4. Run `/bridge` in the client to confirm. You should see
   `Game bridge: CONNECTED`.

**A fresh save is recommended but no longer required.** The bridge only
credits a dexsanity check for a species you have genuinely caught in a run
this session -- it specifically ignores PokeRogue's own free-starter bootstrap
(the handful of species every new save starts with already marked caught), so
those no longer fire checks for free. Species you legitimately caught in
*previous, non-AP* play on the same save will still credit their checks
immediately on first connect, since that is real catch history. If you'd
rather start clean, use Settings -> Offline -> Clear All Data.

## Playing

Start a **Classic** run. Only Classic counts -- Endless, Daily and Challenge
runs send nothing and cannot complete the goal.

In starter select, species you have not been granted will refuse to be added to
your party. Use `/unlocked` in the client to see your current roster.

## Changing the bridge port

If port 17777 is taken, start the client with `--bridge_port 12345` and set the
matching value in-game by running this in the game's developer console:

```js
localStorage.setItem("ap_bridge_port", "12345");
```

Then reload the game.

## Troubleshooting

**The client says the game is running but has not connected.** The build is not
patched, or was built before the patch was registered in `apply-patches.sh`.

**`Could not listen on ws://127.0.0.1:17777`.** Another PokeRogue client is
already running. Close it.

**Checks are not sending.** Confirm you are in Classic mode, and that `/bridge`
reports a connection. The bridge polls once per second, so allow a moment.

**A bunch of dexsanity checks fired at once on connect.** You joined with a
save that had real catch history from before this AP session (not PokeRogue's
free-starter bootstrap, which the bridge already ignores -- see "A fresh save
is recommended" above). This is expected: those species were genuinely caught,
so they credit immediately. Use Clear All Data first if you'd rather not.

**A species I should have doesn't show as available.** The starter select
screen may have already built its list before the grant applied. Back out to
the title and reopen starter select, or run `/resync` in the client.

**My level cap isn't rising / Progressive Level Cap doesn't seem to fit.**
Confirm Dexsanity is off for this slot (`/levelcap` reports "not active" when
it's on) and that you're in a Classic run, not Endless or Daily.

---

## Alternative: the userscript (not recommended)

A Tampermonkey userscript is included for playing on the official website or an
unpatched build. It reads the save out of `localStorage` and reports checks the
same way.

**It cannot enforce the species lock.** Blocking a starter selection requires
changing the game's input handling, which is only possible in the patched build.
The userscript shows you which species are locked and warns you, but nothing
stops you from choosing one. Enforcement is on the honour system.

Use it only if you cannot build the patched client. To install: add
`pokerogue-ap.user.js` to Tampermonkey, then start the PokeRogue Client as
normal. `window.__APCheck(speciesId)` in the console reports whether a given
species is unlocked.
