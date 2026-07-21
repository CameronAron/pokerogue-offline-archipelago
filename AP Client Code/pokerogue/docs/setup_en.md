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

1. Clone [pokerogue-offline](https://github.com/PokeRogue-Offline/pokerogue-offline).
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

The patch is idempotent and fails loudly. If upstream PokeRogue has changed
enough that an anchor no longer matches, the build stops with a message naming
the anchor rather than silently producing a broken exe.

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

**Start a fresh save.** The bridge reports every species currently marked caught
in your Pokedex, so joining with a save that already has a full Pokedex will
instantly send every dexsanity check you have. Use Settings -> Offline -> Clear
All Data before your first run, or start from a clean install.

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

**All my dexsanity checks fired at once.** You joined with an existing save that
already had those species caught. See "Start a fresh save" above.

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
