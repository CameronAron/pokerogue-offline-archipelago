# PokeRogue Setup Guide

## Required software

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.7 or
  newer.
- The `pokerogue.apworld` file from this release.
- The **patched PokeRogue Archipelago desktop build**. You can download this from `releases`

## How this works

PokeRogue runs as JavaScript inside an Electron window, so there is no game
memory for a client to read the way an emulator client would. Instead the
patched game opens a WebSocket back to the Archipelago client:

```
Archipelago server  <--->  PokeRogue Client  <--->  the game
                              (Python)          (localhost:17777)
```

The client holds the authoritative state. The game is told the full unlock
set every time it changes, so crashing, reloading, or reconnecting mid-run
all recover correctly on their own.

## Installing the apworld

Double-click `pokerogue.apworld`, or copy it into your Archipelago install's
`custom_worlds` folder. Restart the Archipelago Launcher afterwards.

## Running the patched game

The PokeRogue Offline project builds by cloning upstream PokeRogue and
applying a set of patches to it. Archipelago support is a few more patches in
that pipeline, touching two existing game files plus two UI files, and adding
one new module.

Download the `PokeRogueArchipelago.exe` app from the releases tab

## Joining a multiworld

1. Start the **PokeRogue Client** from the Archipelago Launcher.
2. Enter the server address and your slot name when prompted.
3. Launch the patched PokeRogue build. It connects automatically.
4. Run `/bridge` in the client to confirm. You should see
   `Game bridge: CONNECTED`.

**A fresh save is required.** If you don't have a fresh save before starting 
with the standalone app, your multiworld will release unintended checks. 
Use `Settings -> Offline -> Clear All Data` to restart your standalone save.

## Playing

Start a **Classic** run. Only Classic counts -- Endless, Daily and Challenge
runs send nothing and cannot complete the goal.

With Dexsanity on, species you haven't been granted refuse to join your
starter team, and a wild catch of a locked species won't join your party
either (the catch still happens normally, it just doesn't stick). Use
`/unlocked` to see your current roster and `/pending` to see what still needs
catching. With Dexsanity off, none of this applies -- play normally.

## Troubleshooting

**`Could not listen on ws://127.0.0.1:17777`.** Another PokeRogue client is
already running. Close it.

**Checks are not sending.** Confirm you are in Classic mode, and that
`/bridge` reports a connection. The bridge polls once per second, so allow a
moment.

**A bunch of dexsanity checks fired at once on connect.** If this is a save
with real catch history from a *different* multiworld or from non-AP play,
that is a side-effect of not reseting a save file.

**A species I should have doesn't show as available.** The starter select
screen may have already built its list before the grant applied. Back out to
the title and reopen starter select, or run `/resync` in the client.

**My level cap isn't rising / Progressive Level Cap doesn't seem to apply.**
Confirm Progressive Level Cap is turned on for this slot (`/levelcap` reports
if it's off) and that you're in a Classic run, not Endless or Daily.
