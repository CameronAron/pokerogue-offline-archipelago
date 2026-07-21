/**
 * Archipelago bridge for PokeRogue Offline.
 *
 * Runs inside the Electron renderer (or a browser userscript build) and talks
 * to the Archipelago PokeRogue client over a localhost WebSocket. The client
 * owns all authoritative state; this module only:
 *
 *   1. observes the live game and reports events (catches, waves, victory), and
 *   2. enforces the species lock locally using the unlock set the client sends.
 *
 * Design notes
 * ------------
 * Almost everything here is *polled* off `globalScene` rather than hooked into
 * game internals. PokeRogue's `main` branch moves fast, and a poller that reads
 * public state degrades gracefully across versions where a patched call site
 * would simply fail to apply. Only the species gate and the victory notify are
 * real source patches, because neither can be done by observation alone.
 *
 * All reporting is idempotent: we send the *current* state (every caught
 * species, the current wave) rather than deltas, and the client de-duplicates
 * against locations it has already checked. That makes crashes, reloads and
 * mid-run reconnects self-healing.
 */

import { globalScene } from "#app/global-scene";

const BRIDGE_VERSION = "0.1.0";
const DEFAULT_PORT = 17777;
const POLL_INTERVAL_MS = 1000;
const RECONNECT_DELAY_MS = 3000;

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
  /** Species the player may currently use. */
  unlocked: Set<number>;
  /** Species that can ever be unlocked this seed. Everything else is dead. */
  pool: Set<number>;
  /** Species that have a dexsanity check attached. */
  dexsanitySpecies: Set<number>;
}

const state: ApState = {
  connected: false,
  slot: null,
  goalWave: 200,
  dexsanity: true,
  deathLink: false,
  unlocked: new Set<number>(),
  pool: new Set<number>(),
  dexsanitySpecies: new Set<number>(),
};

let socket: WebSocket | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** Last values we reported, so we only send on change. */
let lastReportedWave = -1;
let lastReportedCaught = new Set<number>();
let sessionActive = false;

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

/**
 * Whether the player is allowed to put this species on their team.
 *
 * Returns true when AP is not active so that unpatched/offline play is
 * unaffected. A species outside the seed's pool can never be unlocked.
 */
export function apIsSpeciesUnlocked(speciesId: number): boolean {
  if (!state.connected) {
    return true;
  }
  return state.unlocked.has(speciesId);
}

/** True if the species exists in this seed at all (used for UI shading). */
export function apIsSpeciesInPool(speciesId: number): boolean {
  if (!state.connected) {
    return true;
  }
  return state.pool.has(speciesId);
}

/** Short label explaining why a species is unavailable, for tooltips. */
export function apLockReason(speciesId: number): string | null {
  if (!state.connected) {
    return null;
  }
  if (!state.pool.has(speciesId)) {
    return "Not in this Archipelago seed";
  }
  if (!state.unlocked.has(speciesId)) {
    return "Locked - unlock item not yet received";
  }
  return null;
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
      state.pool = new Set<number>((msg.pool_species ?? []).map(Number));
      state.dexsanitySpecies = new Set<number>(
        Object.keys(msg.dexsanity_species ?? {}).map(Number),
      );
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
 * Collect every species currently marked caught in the Pokedex.
 *
 * `caughtAttr` is a BigInt bitfield; any nonzero value means caught. We only
 * care about species that carry a dexsanity check in this seed.
 */
function collectCaughtSpecies(gameData: any): Set<number> {
  const caught = new Set<number>();
  const dexData = gameData?.dexData;
  if (!dexData) {
    return caught;
  }

  for (const speciesId of state.dexsanitySpecies) {
    const entry = dexData[speciesId];
    if (!entry) {
      continue;
    }
    try {
      if (BigInt(entry.caughtAttr ?? 0) !== 0n) {
        caught.add(speciesId);
      }
    } catch {
      // Non-BigInt-coercible value; fall back to a loose truthiness check.
      if (entry.caughtAttr) {
        caught.add(speciesId);
      }
    }
  }
  return caught;
}

function poll(): void {
  if (!state.connected) {
    return;
  }

  const s = scene();
  if (!s) {
    return;
  }

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

  // ── Wave milestones ──────────────────────────────────────────────────────
  try {
    const battle = s.currentBattle;
    const mode = s.gameMode;
    if (battle && mode?.isClassic) {
      sessionActive = true;
      const wave = Number(battle.waveIndex ?? 0);
      if (wave > 0 && wave !== lastReportedWave) {
        lastReportedWave = wave;
        send({ cmd: "Wave", wave, mode: "classic" });
      }
    } else if (!battle) {
      sessionActive = false;
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

export { sessionActive };
