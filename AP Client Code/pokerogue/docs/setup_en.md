# PokeRogue Setup Guide

## What you need

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.4 or newer.
- The latest release from this repo's [Releases page](../../releases), which includes both the game and the apworld together.

## How this works

PokeRogue runs as JavaScript inside an Electron window. The game talks to Archipelago over a local WebSocket connection to the PokeRogue Client, so the client always knows exactly what's been unlocked and can tell the game about it in real time.

```
Archipelago server  <--->  PokeRogue Client  <--->  the game
                              (Python)          (localhost:17777)
```

The client is the source of truth. It works out what you've unlocked from the items you've received and sends the full picture to the game whenever something changes. If the game crashes, reloads, or reconnects, it just asks for that picture again rather than trying to remember anything itself.

## Installing

1. Download the latest release and unzip it wherever you like.
2. Copy `pokerogue.apworld` into your Archipelago install's `custom_worlds` folder, then restart the Archipelago Launcher.
3. That's it for the game itself — the download already has Archipelago support built in.

## Joining a multiworld

1. Start **PokeRogue Client** from the Archipelago Launcher.
2. Enter your server address and slot name.
3. Launch the game from wherever you unzipped it. It connects on its own.
4. Type `/bridge` in the client to confirm — you should see `Game bridge: CONNECTED`.

A fresh save isn't required. The game tags your save with the multiworld it's connected to, and the first time it sees a save that isn't tagged (or is tagged for a different multiworld), it quietly treats whatever's already caught as a starting point instead of firing checks for it. So reusing a save across different multiworlds, or picking up an old save from outside Archipelago entirely, won't dump a pile of checks on you the moment you connect.

## Playing

Start a **Classic** run — Endless, Daily, and Challenge don't send checks and can't complete your goal.

With Dexsanity on, species you haven't been granted can't be added to your starting team, and a wild catch of a locked species won't join your party either — the catch still happens, it just doesn't stick. `/unlocked` shows your current roster, `/pending` shows what's still needed for a check. With Dexsanity off, none of that applies and you play normally.

## Client commands

- `/bridge` — connection status
- `/unlocked` — species you've been granted
- `/pending` — species you still need to catch for a check
- `/expgain` — your current EXP gain rate, if Progressive EXP Gain is on
- `/resync` — force a full state refresh to the game
- `/rebaseline` — re-exclude whatever's currently caught from firing checks, without wiping your save (see Troubleshooting)

## Changing the bridge port

If 17777 is already taken, start the client with `--bridge_port 12345`, then run this in the game's developer console and reload:

```js
localStorage.setItem("ap_bridge_port", "12345");
```

## Troubleshooting

**The client sees the game running but it won't connect.** Make sure you're running the game from this release, not an older download or an unrelated PokeRogue build.

**`Could not listen on ws://127.0.0.1:17777`.** Another PokeRogue client is already running somewhere. Close it and try again.

**Checks aren't sending.** Make sure you're in a Classic run and that `/bridge` shows a connection. The game checks in about once a second, so give it a moment.

**A bunch of dexsanity checks fired the moment I connected.** If this is a save with real catch history from a different multiworld, that's expected the first time you connect to the new one — those species were genuinely caught, so they count. It shouldn't happen again on later reconnects to the same multiworld. If it does, run `/rebaseline` and check the game's own console for lines starting with `[Archipelago] baseline:` — they'll show whether the game recognizes the multiworld you're connected to.

**A species I should have doesn't show as available.** The starter select screen may have built its list before the grant came through. Back out to the title and reopen it, or run `/resync`.

**My EXP gain rate isn't moving.** Confirm Progressive EXP Gain is turned on for this slot — `/expgain` will tell you if it's off — and that you're in a Classic run.
