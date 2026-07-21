/**
 * Archipelago bridge for PokeRogue Offline.
 *
 * Runs inside the Electron renderer (or a browser userscript build) and talks
 * to the Archipelago PokeRogue client over a localhost WebSocket. The client
 * owns all authoritative state; this module only:
 *
 *   1. observes the live game and reports events (catches, waves, victory), and
 *   2. enforces species availability and (in one mode) the level cap locally,
 *      using the state the client sends.
 *
 * Design notes
 * ------------
 * Almost everything here is *polled* off `globalScene` rather than hooked into
 * game internals. PokeRogue's `main` branch moves fast, and a poller that reads
 * public state degrades gracefully across versions where a patched call site
 * would simply fail to apply. The only real source patch left is the victory/
 * defeat notify in game-over-phase.ts -- everything else, including the
 * species lock and the level cap, is done by this module driving the game's
 * own data structures directly, which means the game's own UI enforces
 * everything for free instead of needing a second parallel gate.
 *
 * The species gate specifically: PokeRogue already refuses to let you select
 * an uncaught species as a starter (`dexData[id].caughtAttr === 0n`). Rather
 * than add a second condition next to that check, this module *drives*
 * caughtAttr directly -- granting it for AP-unlocked species and forcing it to
 * zero for everything else, every poll tick. That means the vanilla UI's own
 * gating becomes the enforcement, with no source patch needed for it at all,
 * and it correctly overrides PokeRogue's own free starter bootstrap (a fixed
 * handful of species come pre-caught on every new save).
 *
 * Dexsanity catch-detection intentionally reads `caughtCount`, not
 * `caughtAttr`. `caughtCount` only increments through a real in-run catch
 * (see `setPokemonSpeciesCaught` in the game source) -- never through the
 * vanilla free-starter bootstrap and never through this module's own grants.
 * That keeps "did the player actually catch one" fully decoupled from "is
 * this species currently allowed", so the two mechanisms can run every tick
 * without ordering concerns or false-positive checks.
 *
 * All reporting is idempotent: we send the *current* state (every caught
 * species, the current wave) rather than deltas, and the client de-duplicates
 * against locations it has already checked. That makes crashes, reloads and
 * mid-run reconnects self-healing.
 */

import { AbilityAttr } from "#enums/ability-attr";
import { DexAttr } from "#enums/dex-attr";
import { globalScene } from "#app/global-scene";

const BRIDGE_VERSION = "0.2.0";
const DEFAULT_PORT = 17777;
const POLL_INTERVAL_MS = 1000;
const RECONNECT_DELAY_MS = 3000;

/** The same bitmask PokeRogue itself grants to `defaultStarterSpecies` on a
 * fresh save (see `initDexData`): non-shiny, either gender, default variant
 * and form. AP grants mirror this exactly, so a granted species looks and
 * behaves like a normal, ordinarily-caught starter. */
const GRANT_DEX_ATTR: bigint =
  DexAttr.NON_SHINY | DexAttr.MALE | DexAttr.FEMALE | DexAttr.DEFAULT_VARIANT | DexAttr.DEFAULT_FORM;
const GRANT_ABILITY_ATTR: number = AbilityAttr.ABILITY_1;

/** Overridable for testing / non-default ports via localStorage. */
function bridgePort(): number {
  try {
    const stored = localStorage.getItem("ap_bridge_port");
    if (stored) {
      const parsed = Number.parseInt(stored, 10);
      if (Number.isFinite(parsed) && parsed > 0 && parsed < 65536) {
        return parsed;
      }
    }
  } catch {
    /* localStorage unavailable; fall through to the default */
  }
  return DEFAULT_PORT;
}

interface ApState {
  connected: boolean;
  slot: string | null;
  goalWave: number;
  dexsanity: boolean;
  deathLink: boolean;
  /** Species the player may currently use. Sole source of truth for the gate. */
  unlocked: Set<number>;
  /** Every species the gate manages at all, regardless of mode. */
  allStarters: Set<number>;
  /** Species that have a dexsanity check attached (empty when dexsanity is off). */
  dexsanitySpecies: Set<number>;
  /** Copies of Progressive Level Cap received so far. */
  levelCapCount: number;
  /** Vanilla wave-block level cap values, tier 1 first. Empty when dexsanity is on. */
  levelCapTiers: number[];
}

const state: ApState = {
  connected: false,
  slot: null,
  goalWave: 200,
  dexsanity: true,
  deathLink: false,
  unlocked: new Set<number>(),
  allStarters: new Set<number>(),
  dexsanitySpecies: new Set<number>(),
  levelCapCount: 0,
  levelCapTiers: [],
};

let socket: WebSocket | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** Last catch set we reported, so we only send on change. */
let lastReportedCaught = new Set<number>();
let lastReportedWave = -1;

// ─────────────────────────────────────────────────────────────── public API

/**
 * Whether the Archipelago bridge is currently driving this game.
 *
 * When false the game must behave exactly like vanilla -- a player who is not
 * in a multiworld should never notice this module exists.
 */
export function apIsActive(): boolean {
  return state.connected;
}

/** Whether the player is currently allowed to use this species. Read-only;
 * the gate itself is enforced by writing dexData directly (see below), so
 * nothing needs to call this to block a selection anymore. Exposed for any
 * future UI (e.g. a locked-species indicator) that wants to read it. */
export function apIsSpeciesUnlocked(speciesId: number): boolean {
  if (!state.connected) {
    return true;
  }
  return state.unlocked.has(speciesId);
}

/** Short label explaining why a species is unavailable, for a future tooltip. */
export function apLockReason(speciesId: number): string | null {
  if (!state.connected || !state.allStarters.has(speciesId)) {
    return null;
  }
  return state.unlocked.has(speciesId) ? null : "Locked - unlock item not yet received";
}

/** Called by the patched GameOverPhase on a Classic victory. */
export function apNotifyVictory(wave: number): void {
  send({ cmd: "Victory", mode: "classic", wave });
}

/** Called by the patched GameOverPhase on a run-ending loss (DeathLink). */
export function apNotifyDefeat(wave: number): void {
  if (state.deathLink) {
    send({ cmd: "Death", cause: `lost a Classic run at wave ${wave}` });
  }
}

// ──────────────────────────────────────────────────────────── socket plumbing

function send(payload: Record<string, unknown>): void {
  if (socket?.readyState === WebSocket.OPEN) {
    try {
      socket.send(JSON.stringify(payload));
    } catch {
      /* the poller will notice the socket died and reconnect */
    }
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer !== null) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_DELAY_MS);
}

function connect(): void {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  let ws: WebSocket;
  try {
    ws = new WebSocket(`ws://127.0.0.1:${bridgePort()}`);
  } catch {
    scheduleReconnect();
    return;
  }
  socket = ws;

  ws.onopen = () => {
    let gameVersion = "unknown";
    try {
      gameVersion = (globalThis as any).__AP_GAME_VERSION__ ?? "unknown";
    } catch {
      /* ignore */
    }
    send({ cmd: "Hello", bridgeVersion: BRIDGE_VERSION, gameVersion });
  };

  ws.onmessage = event => {
    try {
      handleMessage(JSON.parse(String(event.data)));
    } catch {
      /* malformed frame; ignore rather than break the game loop */
    }
  };

  ws.onclose = () => {
    state.connected = false;
    state.slot = null;
    socket = null;
    resetReportCache();
    scheduleReconnect();
  };

  ws.onerror = () => {
    // onclose always follows, which handles the reconnect.
  };
}

function resetReportCache(): void {
  lastReportedWave = -1;
  lastReportedCaught = new Set<number>();
}

function handleMessage(msg: Record<string, any>): void {
  switch (msg.cmd) {
    case "State": {
      state.connected = Boolean(msg.connected);
      state.slot = msg.slot ?? null;
      state.goalWave = Number(msg.goal_wave ?? 200);
      state.dexsanity = Boolean(msg.dexsanity);
      state.deathLink = Boolean(msg.death_link);
      state.unlocked = new Set<number>((msg.unlocked_species ?? []).map(Number));
      state.allStarters = new Set<number>((msg.all_starter_species ?? []).map(Number));
      state.dexsanitySpecies = new Set<number>(
        Object.keys(msg.dexsanity_species ?? {}).map(Number),
      );
      state.levelCapCount = Number(msg.level_cap_count ?? 0);
      state.levelCapTiers = (msg.level_cap_tiers ?? []).map(Number);
      // A fresh state push may reveal checks we never reported (e.g. the
      // client restarted); clear the cache so the next poll re-reports.
      resetReportCache();
      break;
    }

    case "DeathLink": {
      // Purely cosmetic on our side: PokeRogue has no safe "kill the run"
      // primitive that wouldn't corrupt a session, so we surface a message
      // instead of forcing a game over.
      showMessage(`DeathLink: ${msg.source ?? "someone"} died.`);
      break;
    }

    default:
      break;
  }
}

function showMessage(text: string): void {
  try {
    // Non-fatal cosmetic hook; the game may not have a UI up yet.
    console.info(`[Archipelago] ${text}`);
  } catch {
    /* ignore */
  }
}

// ───────────────────────────────────────────────────────────────── polling

/** Safely read the live BattleScene, or null if the game isn't ready. */
function scene(): any | null {
  try {
    const s: any = globalScene;
    return s ?? null;
  } catch {
    return null;
  }
}

/**
 * Collect every species with at least one genuine in-run catch this session.
 *
 * Deliberately reads `caughtCount`, a plain counter that real catches
 * increment and nothing else touches (see module doc comment) -- so this is
 * immune both to the vanilla free-starter bootstrap and to this module's own
 * grants below.
 */
function collectCaughtSpecies(gameData: any): Set<number> {
  const caught = new Set<number>();
  const dexData = gameData?.dexData;
  if (!dexData) {
    return caught;
  }

  for (const speciesId of state.dexsanitySpecies) {
    const entry = dexData[speciesId];
    if (entry && Number(entry.caughtCount ?? 0) > 0) {
      caught.add(speciesId);
    }
  }
  return caught;
}

/**
 * Grant or lock every species the gate manages, every tick.
 *
 * Grant: OR in the baseline "usable starter" bits, never subtracting from
 * whatever the game already recorded through real play.
 *
 * Lock: force caughtAttr to zero, regardless of how it got set -- the vanilla
 * bootstrap, a real catch of an as-yet-ungranted species, or a previous
 * grant that has since been revoked (should not normally happen, but the
 * sweep is idempotent either way).
 *
 * `seenAttr` is left untouched either direction: a locked species the player
 * has encountered in the wild still shows a normal "seen" silhouette, which
 * is cosmetic and does not affect selectability.
 */
function enforceSpeciesGate(gameData: any): void {
  const dexData = gameData?.dexData;
  const starterData = gameData?.starterData;
  if (!dexData || !starterData) {
    return;
  }

  for (const speciesId of state.allStarters) {
    const dexEntry = dexData[speciesId];
    if (!dexEntry) {
      continue;
    }

    if (state.unlocked.has(speciesId)) {
      dexEntry.caughtAttr = BigInt(dexEntry.caughtAttr ?? 0) | GRANT_DEX_ATTR;
      const starterEntry = starterData[speciesId];
      if (starterEntry) {
        starterEntry.abilityAttr = Number(starterEntry.abilityAttr ?? 0) | GRANT_ABILITY_ATTR;
      }
    } else {
      dexEntry.caughtAttr = 0n;
    }
  }
}

/**
 * Install (once) a wrapper around `globalScene.getMaxExpLevel` that clamps
 * the result to the AP-granted level cap tier when Progressive Level Cap is
 * active. Left untouched -- returns the vanilla wave-based value -- when
 * dexsanity is on, when the caller explicitly asked to ignore the cap (this
 * is how Rare Candy already bypasses it in vanilla), or before AP connects.
 *
 * This patches the live scene instance rather than the source, since
 * `getMaxExpLevel` is a pure function of public state; wrapping the bound
 * instance method survives every internal call site (`this.getMaxExpLevel()`
 * resolves through the instance first) without touching battle-scene.ts at
 * all. Idempotent via a marker property, and self-reinstalls if the scene is
 * ever recreated (e.g. a full page reload swaps out `globalScene`).
 */
function installLevelCapOverride(s: any): void {
  if (s.__apLevelCapPatched) {
    return;
  }
  const original: (ignoreLevelCap?: boolean) => number = s.getMaxExpLevel.bind(s);
  s.getMaxExpLevel = (ignoreLevelCap = false): number => {
    const vanilla = original(ignoreLevelCap);
    if (ignoreLevelCap || !state.connected || state.levelCapTiers.length === 0) {
      return vanilla;
    }
    const tier = Math.min(state.levelCapCount, state.levelCapTiers.length - 1);
    return Math.min(vanilla, state.levelCapTiers[tier]);
  };
  s.__apLevelCapPatched = true;
}

function poll(): void {
  if (!state.connected) {
    return;
  }

  const s = scene();
  if (!s) {
    return;
  }

  installLevelCapOverride(s);

  // ── Dexsanity ────────────────────────────────────────────────────────────
  if (state.dexsanity) {
    try {
      const caught = collectCaughtSpecies(s.gameData);
      for (const speciesId of caught) {
        if (!lastReportedCaught.has(speciesId)) {
          send({ cmd: "Catch", speciesId });
        }
      }
      lastReportedCaught = caught;
    } catch {
      /* dex not ready yet */
    }
  }

  // ── Species gate ─────────────────────────────────────────────────────────
  try {
    enforceSpeciesGate(s.gameData);
  } catch {
    /* game data not ready yet */
  }

  // ── Wave milestones ──────────────────────────────────────────────────────
  try {
    const battle = s.currentBattle;
    const mode = s.gameMode;
    if (battle && mode?.isClassic) {
      const wave = Number(battle.waveIndex ?? 0);
      if (wave > 0 && wave !== lastReportedWave) {
        lastReportedWave = wave;
        send({ cmd: "Wave", wave, mode: "classic" });
      }
    } else if (!battle) {
      lastReportedWave = -1;
    }
  } catch {
    /* not in a run */
  }
}

// ──────────────────────────────────────────────────────────────── bootstrap

function start(): void {
  if (pollTimer !== null) {
    return;
  }
  connect();
  pollTimer = setInterval(poll, POLL_INTERVAL_MS);

  // Expose a tiny surface for debugging and for the userscript build, which
  // cannot import ES modules from the bundle.
  try {
    (globalThis as any).__AP__ = {
      version: BRIDGE_VERSION,
      state,
      isActive: apIsActive,
      isSpeciesUnlocked: apIsSpeciesUnlocked,
      resync: () => send({ cmd: "Sync" }),
    };
  } catch {
    /* ignore */
  }
}

start();
