"""Archipelago client for PokeRogue (standalone offline desktop build).

Architecture
------------
The game runs as JavaScript inside an Electron renderer, so there is no process
memory to read the way a console emulator client would. Instead the patched
game opens a WebSocket back to this client:

    Archipelago server  <--websocket-->  THIS CLIENT  <--websocket-->  game

This client is therefore two things at once:

* a normal ``CommonContext`` talking the Archipelago protocol, and
* a small localhost WebSocket *server* (default 127.0.0.1:17777) that the
  in-game bridge connects to.

Authoritative state lives here, not in the game. The game is told the full set
of unlocked species every time it changes, so a reconnect, a mid-run crash, or
a fresh save all converge to the correct state without replaying history.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from typing import Any

import Utils
from CommonClient import (
    ClientCommandProcessor,
    CommonContext,
    get_base_parser,
    gui_enabled,
    logger,
    server_loop,
)
from NetUtils import ClientStatus, NetworkItem

DEFAULT_BRIDGE_PORT = 17777

#: Executable names that indicate the game is running. Purely informational --
#: the bridge connection is what actually matters -- but it lets the client say
#: something useful when the game is open but the patch is missing.
GAME_PROCESS_NAMES = (
    "pokerogueoffline.exe",
    "pokerogueoffline-dev.exe",
    "pokerogue offline.exe",
    "pokerogue.exe",
    "pokerogueoffline",
    "pokerogue offline",
)


def find_game_process() -> str | None:
    """Return the name of a running PokeRogue process, if we can find one.

    psutil is an optional dependency of some Archipelago installs, so a missing
    import must never be fatal -- it only degrades the status message.
    """
    try:
        import psutil
    except ImportError:
        return None

    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in GAME_PROCESS_NAMES:
                return proc.info["name"]
    except Exception:
        return None
    return None


class PokeRogueCommandProcessor(ClientCommandProcessor):
    def _cmd_bridge(self) -> None:
        """Show the status of the connection to the game."""
        ctx: PokeRogueContext = self.ctx
        if ctx.game_connected:
            logger.info(
                "Game bridge: CONNECTED (game version %s)", ctx.game_version or "unknown"
            )
        else:
            logger.info("Game bridge: not connected (listening on %s)", ctx.bridge_url)
            proc = find_game_process()
            if proc:
                logger.info(
                    "  PokeRogue appears to be running (%s) but has not connected. "
                    "Is this an Archipelago-patched build?",
                    proc,
                )
            else:
                logger.info("  PokeRogue does not appear to be running.")

    def _cmd_unlocked(self) -> None:
        """List the species you have been granted so far."""
        ctx: PokeRogueContext = self.ctx
        if not ctx.unlocked_species:
            logger.info("No species unlocked yet.")
            return
        names = sorted(ctx.species_display(sid) for sid in ctx.unlocked_species)
        logger.info("Unlocked %d species: %s", len(names), ", ".join(names))

    def _cmd_resync(self) -> None:
        """Force a full state push to the game."""
        ctx: PokeRogueContext = self.ctx
        ctx.queue_push_state()
        logger.info("Resync queued.")


class PokeRogueContext(CommonContext):
    command_processor = PokeRogueCommandProcessor
    game = "PokeRogue"
    items_handling = 0b111  # full remote item handling

    def __init__(self, server_address: str | None, password: str | None, bridge_port: int):
        super().__init__(server_address, password)
        self.bridge_port = bridge_port

        # --- game bridge state ---
        self.game_socket: Any = None
        self.game_connected: bool = False
        self.game_version: str | None = None
        self.bridge_server: Any = None

        # --- slot data, populated on Connected ---
        self.slot_data: dict[str, Any] = {}
        self.goal_wave: int = 200
        self.dexsanity: bool = True
        #: numeric SpeciesId -> AP location id
        self.dexsanity_species: dict[int, int] = {}
        #: AP item id -> numeric SpeciesId
        self.species_items: dict[int, int] = {}
        #: wave number -> AP location id
        self.wave_locations: dict[int, int] = {}
        self.pool_species: list[int] = []

        #: Species the player is currently allowed to use.
        self.unlocked_species: set[int] = set()
        #: Filler item names received, for display in-game.
        self.pending_notifications: list[dict[str, Any]] = []

        self.goal_reached: bool = False
        self._push_pending = asyncio.Event()

    @property
    def bridge_url(self) -> str:
        return f"ws://127.0.0.1:{self.bridge_port}"

    # ------------------------------------------------------------ AP protocol

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", {}) or {}
            self._apply_slot_data(self.slot_data)
            self.unlocked_species = set()
            self.recompute_unlocks()
            self.queue_push_state()

        elif cmd == "ReceivedItems":
            self.recompute_unlocks()
            self.queue_push_state()

        elif cmd == "RoomUpdate":
            self.recompute_unlocks()
            self.queue_push_state()

    def _apply_slot_data(self, data: dict[str, Any]) -> None:
        self.goal_wave = int(data.get("goal_wave", 200))
        self.dexsanity = bool(data.get("dexsanity", True))
        self.dexsanity_species = {
            int(k): int(v) for k, v in (data.get("dexsanity_species") or {}).items()
        }
        self.species_items = {
            int(k): int(v) for k, v in (data.get("species_items") or {}).items()
        }
        self.wave_locations = {
            int(k): int(v) for k, v in (data.get("wave_locations") or {}).items()
        }
        self.pool_species = [int(x) for x in (data.get("pool_species") or [])]

        logger.info(
            "Slot configured: goal wave %d, dexsanity %s, %d species in pool.",
            self.goal_wave,
            "on" if self.dexsanity else "off",
            len(self.pool_species),
        )

    def species_display(self, species_id: int) -> str:
        """Human-readable species name, resolved through the datapackage."""
        for item_id, sid in self.species_items.items():
            if sid == species_id:
                name = self.item_names.lookup_in_game(item_id, self.game)
                if name:
                    return name.removesuffix(" Unlock")
        return f"Species #{species_id}"

    def recompute_unlocks(self) -> None:
        """Rebuild the unlocked-species set from scratch out of items_received.

        Rebuilding rather than incrementing means a reconnect or a resend can
        never leave the game out of sync with the server.
        """
        unlocked: set[int] = set()
        notifications: list[dict[str, Any]] = []

        for item in self.items_received:
            species_id = self.species_items.get(item.item)
            if species_id is not None:
                unlocked.add(species_id)
            else:
                name = self.item_names.lookup_in_game(item.item, self.game)
                if name:
                    notifications.append({"name": name, "id": item.item})

        newly = unlocked - self.unlocked_species
        for species_id in sorted(newly):
            logger.info("Unlocked: %s", self.species_display(species_id))

        self.unlocked_species = unlocked
        self.pending_notifications = notifications

    def queue_push_state(self) -> None:
        self._push_pending.set()

    def on_print_json(self, args: dict) -> None:
        super().on_print_json(args)

    # ------------------------------------------------------------ deathlink

    async def send_death(self, death_text: str = "") -> None:
        await super().send_death(death_text)

    def on_deathlink(self, data: dict[str, Any]) -> None:
        super().on_deathlink(data)
        asyncio.create_task(
            self.send_to_game(
                {
                    "cmd": "DeathLink",
                    "source": data.get("source", "someone"),
                    "cause": data.get("cause", ""),
                }
            )
        )

    # ---------------------------------------------------------- game bridge

    async def send_to_game(self, payload: dict[str, Any]) -> None:
        socket = self.game_socket
        if socket is None:
            return
        try:
            await socket.send(json.dumps(payload))
        except Exception:
            # The game closing mid-send is normal; the handler cleans up.
            pass

    def build_state_payload(self) -> dict[str, Any]:
        return {
            "cmd": "State",
            "connected": self.slot is not None,
            "slot": self.slot_info[self.slot].name if self.slot in self.slot_info else None,
            "goal_wave": self.goal_wave,
            "dexsanity": self.dexsanity,
            "death_link": "DeathLink" in self.tags,
            # Everything the bridge needs to enforce gating locally.
            "unlocked_species": sorted(self.unlocked_species),
            "pool_species": self.pool_species,
            "dexsanity_species": {str(k): v for k, v in self.dexsanity_species.items()},
            "wave_locations": {str(k): v for k, v in self.wave_locations.items()},
            "checked_locations": sorted(self.checked_locations),
            "notifications": self.pending_notifications,
        }

    async def push_state_loop(self) -> None:
        """Push authoritative state to the game whenever it changes."""
        while not self.exit_event.is_set():
            try:
                await asyncio.wait_for(self._push_pending.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            self._push_pending.clear()
            if self.game_connected:
                await self.send_to_game(self.build_state_payload())

    async def handle_game_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Bad message from game: %r", raw[:200])
            return

        cmd = msg.get("cmd")

        if cmd == "Hello":
            self.game_version = msg.get("gameVersion")
            logger.info(
                "Game connected (PokeRogue %s, bridge %s).",
                self.game_version or "unknown",
                msg.get("bridgeVersion", "?"),
            )
            await self.send_to_game(self.build_state_payload())

        elif cmd == "Catch":
            await self.handle_catch(int(msg.get("speciesId", 0)))

        elif cmd == "Wave":
            await self.handle_wave(int(msg.get("wave", 0)), msg.get("mode"))

        elif cmd == "Victory":
            await self.handle_victory(msg)

        elif cmd == "Death":
            if "DeathLink" in self.tags:
                await self.send_death(msg.get("cause") or "lost a run in PokeRogue.")

        elif cmd == "Sync":
            await self.send_to_game(self.build_state_payload())

        elif cmd == "Log":
            logger.info("[game] %s", msg.get("text", ""))

    async def handle_catch(self, species_id: int) -> None:
        if not species_id or not self.dexsanity:
            return
        location_id = self.dexsanity_species.get(species_id)
        if location_id is None:
            return  # species not in this seed's pool
        if location_id in self.checked_locations:
            return
        await self.check_locations([location_id])

    async def handle_wave(self, wave: int, mode: str | None) -> None:
        if mode and mode.lower() != "classic":
            return
        to_send = [
            loc_id
            for wave_num, loc_id in self.wave_locations.items()
            if wave_num <= wave and loc_id not in self.checked_locations
        ]
        if to_send:
            await self.check_locations(to_send)

        if wave >= self.goal_wave and not self.goal_reached:
            # Reaching the goal wave is not the same as clearing it; only the
            # explicit Victory message completes the goal for wave 200. For
            # shorter goals, arriving at the wave is enough.
            if self.goal_wave < 200:
                await self.complete_goal()

    async def handle_victory(self, msg: dict[str, Any]) -> None:
        if (msg.get("mode") or "classic").lower() != "classic":
            return
        wave = int(msg.get("wave", 0))
        if wave < self.goal_wave:
            return
        await self.complete_goal()

    async def complete_goal(self) -> None:
        if self.goal_reached:
            return
        self.goal_reached = True
        logger.info("Goal complete! Classic mode cleared.")
        await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])

    async def check_locations(self, location_ids: list[int]) -> None:
        new = [loc for loc in location_ids if loc not in self.checked_locations]
        if not new:
            return
        await self.send_msgs([{"cmd": "LocationChecks", "locations": new}])
        for loc in new:
            name = self.location_names.lookup_in_game(loc, self.game)
            logger.info("Check: %s", name or loc)

    async def run_bridge_server(self) -> None:
        """Run the localhost WebSocket server the game connects to."""
        import websockets

        async def handler(websocket, *_args):
            if self.game_socket is not None:
                # Only one game at a time; the newest connection wins so that
                # relaunching the game doesn't require restarting the client.
                try:
                    await self.game_socket.close()
                except Exception:
                    pass

            self.game_socket = websocket
            self.game_connected = True
            logger.info("Game bridge connected.")
            try:
                async for raw in websocket:
                    await self.handle_game_message(raw)
            except Exception:
                pass
            finally:
                if self.game_socket is websocket:
                    self.game_socket = None
                    self.game_connected = False
                    self.game_version = None
                    logger.info("Game bridge disconnected.")

        try:
            self.bridge_server = await websockets.serve(handler, "127.0.0.1", self.bridge_port)
        except OSError as exc:
            logger.error(
                "Could not listen on %s: %s. Is another PokeRogue client already running?",
                self.bridge_url,
                exc,
            )
            return

        logger.info("Waiting for PokeRogue on %s", self.bridge_url)
        proc = find_game_process()
        if proc:
            logger.info("PokeRogue is already running (%s); it should connect shortly.", proc)

        await self.exit_event.wait()

    def run_gui(self) -> None:
        from kvui import GameManager

        class PokeRogueManager(GameManager):
            logging_pairs = [("Client", "Archipelago")]
            base_title = "Archipelago PokeRogue Client"

        self.ui = PokeRogueManager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")


async def main(args) -> None:
    ctx = PokeRogueContext(args.connect, args.password, args.bridge_port)
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")

    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()

    bridge_task = asyncio.create_task(ctx.run_bridge_server(), name="BridgeServer")
    push_task = asyncio.create_task(ctx.push_state_loop(), name="PushState")

    await ctx.exit_event.wait()

    for task in (bridge_task, push_task):
        task.cancel()
    if ctx.bridge_server is not None:
        ctx.bridge_server.close()
    await ctx.shutdown()


def launch(*launch_args: str) -> None:
    parser = get_base_parser(description="PokeRogue Archipelago Client")
    parser.add_argument(
        "--bridge_port",
        type=int,
        default=DEFAULT_BRIDGE_PORT,
        help="Localhost port the patched game connects to.",
    )
    args = parser.parse_args(launch_args or None)

    Utils.init_logging("PokeRogueClient", exception_logger="Client")

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    launch(*sys.argv[1:])
