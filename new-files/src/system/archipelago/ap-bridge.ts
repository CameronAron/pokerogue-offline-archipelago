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
 * game internals, because polling public state survives upstream churn far
 * better than a pile of regex anchors would. Three things cannot be done this
 * way, and are the only real source anchors across the whole patch set: the
 * Classic victory/defeat notify in game-over-phase.ts, the party-add refusal
 * in field/pokemon.ts (see apCanAddToParty), and the "still needs catching"
 * icon in enemy-battle-info.ts (see apNeedsCatch). Everything else -- the
 * species lock, the level cap, dexsanity detection -- is this module driving
 * the game's own data structures directly.
 *
 * The species gate: PokeRogue already refuses to let you select an uncaught
 * species as a starter (`dexData[id].caughtAttr === 0n`). Rather than add a
 * second condition next to that check, this module *drives* caughtAttr
 * directly -- granting it for AP-unlocked species and forcing it to zero for
 * everything else, every poll tick. That means the vanilla UI's own gating
 * becomes the enforcement, with no source patch needed for starter select at
 * all, and it correctly overrides PokeRogue's own free starter bootstrap (a
 * fixed handful of species come pre-caught on every new save).
 *
 * The gate is only active when Dexsanity is on. With it off there is no
 * species pool to grow from -- catching and using Pokemon works exactly like
 * vanilla, and the only Archipelago mechanic left is Progressive Level Cap
 * (which is its own independent toggle; see installLevelCapOverride).
 *
 * Dexsanity catch-detection intentionally reads `caughtCount`, not
 * `caughtAttr`. `caughtCount` only increments through a real in-run catch
 * (see `setPokemonSpeciesCaught` in the game source, including its recursive
 * walk up the evolution line -- catching an evolved form credits every
 * prevolution's `caughtCount` too) -- never through the vanilla free-starter
 * bootstrap and never through this module's own grants. That keeps "did the
 * player actually catch one" fully decoupled from "is this species currently
 * allowed", so the two mechanisms can run every tick with no ordering
 * concerns or false-positive checks.
 *
 * A save carried over from a different multiworld (or from non-AP play) is
 * handled by tagging localStorage with the connected room's seed_name: the
 * first time a new or different seed_name is seen, the currently-caught set
 * is captured as a silent baseline instead of being reported, so switching
 * multiworlds on the same save doesn't instantly fire someone else's catch
 * history as checks. See establishBaselineIfNeeded.
 *
 * All reporting is idempotent: we send the *current* state (every caught
 * species, the current wave) rather than deltas, and the client de-duplicates
 * against locations it has already checked. That makes crashes, reloads and
 * mid-run reconnects self-healing.
 */

import { AbilityAttr } from "#enums/ability-attr";
import { DexAttr } from "#enums/dex-attr";
import { SpeciesId } from "#enums/species-id";
import { globalScene } from "#app/global-scene";

const BRIDGE_VERSION = "0.3.0";
const DEFAULT_PORT = 17777;
const POLL_INTERVAL_MS = 1000;
const RECONNECT_DELAY_MS = 3000;
const SEED_TAG_KEY = "ap_seed_tag";
const AP_CHECK_TEXTURE_KEY = "ap_needs_catch_icon";

/** The same bitmask PokeRogue itself grants to `defaultStarterSpecies` on a
 * fresh save (see `initDexData`): non-shiny, either gender, default variant
 * and form. AP grants mirror this exactly, so a granted species looks and
 * behaves like a normal, ordinarily-caught starter. */
const GRANT_DEX_ATTR: bigint =
  DexAttr.NON_SHINY | DexAttr.MALE | DexAttr.FEMALE | DexAttr.DEFAULT_VARIANT | DexAttr.DEFAULT_FORM;
const GRANT_ABILITY_ATTR: number = AbilityAttr.ABILITY_1;
/** Matches the 15/15/15/15/15/15 vanilla defaultStarterSpecies also get. */
const GRANT_IVS: readonly number[] = [15, 15, 15, 15, 15, 15];

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
  seedName: string | null;
  goalWave: number;
  dexsanity: boolean;
  progressiveLevelCap: boolean;
  deathLink: boolean;
  /** Species the player may currently use. Sole source of truth for the gate. */
  unlocked: Set<number>;
  /** Every species the gate manages at all. Empty/unused when dexsanity is off. */
  allStarters: Set<number>;
  /** Species that have a dexsanity check attached (empty when dexsanity is off). */
  dexsanitySpecies: Set<number>;
  /** Species with a dexsanity check that hasn't fired yet -- drives the
   * "still needs catching" icon. */
  pendingDexsanitySpecies: Set<number>;
  /** Copies of Progressive Level Cap received so far. */
  levelCapCount: number;
  /** Vanilla wave-block level cap values, tier 1 first. Empty when the option is off. */
  levelCapTiers: number[];
}

const state: ApState = {
  connected: false,
  slot: null,
  seedName: null,
  goalWave: 200,
  dexsanity: true,
  progressiveLevelCap: false,
  deathLink: false,
  unlocked: new Set<number>(),
  allStarters: new Set<number>(),
  dexsanitySpecies: new Set<number>(),
  pendingDexsanitySpecies: new Set<number>(),
  levelCapCount: 0,
  levelCapTiers: [],
};

let socket: WebSocket | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** Last catch set we reported, so we only send on change. */
let lastReportedCaught = new Set<number>();
let lastReportedWave = -1;
/** Set when a new/different seed_name is seen; consumed on the next poll to
 * silently snapshot current catches instead of reporting them. */
let needsBaselineSnapshot = false;

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

/** Whether the species gate is enforcing anything at all right now. False
 * with no AP session, and false whenever Dexsanity is off -- in that mode
 * there is nothing to grow the roster with, so catching and using Pokemon
 * works exactly like vanilla instead of being gated. */
function gateActive(): boolean {
  return state.connected && state.dexsanity;
}

/** Whether the player is currently allowed to use this species. Read-only;
 * the gate itself is enforced by writing dexData directly (see below) and by
 * apCanAddToParty for in-run catches, so nothing needs to call this to block
 * a selection. Exposed for any future UI that wants to read it. */
export function apIsSpeciesUnlocked(speciesId: number): boolean {
  if (!gateActive()) {
    return true;
  }
  return state.unlocked.has(speciesId);
}

/** Called from the patched `PlayerPokemon.addToParty` to decide whether a
 * catch is allowed to actually join the party. Returning false leaves the
 * catch animation and ball-throw untouched (see the patch site) -- the
 * Pokemon is just never added, exactly like PokeRogue's own "party is full"
 * case already behaves, so no new failure mode is introduced. */
export function apCanAddToParty(speciesId: number): boolean {
  return apIsSpeciesUnlocked(speciesId);
}

/** Called alongside a blocked catch so the *client's* log can tell the player
 * what happened -- an in-game popup risks interfering with the capture
 * phase's own careful UI sequencing, so this is deliberately a side-channel
 * notification rather than a showText call inserted into that flow. */
export function apNotifyLockedCatch(speciesId: number): void {
  send({ cmd: "LockedCatch", speciesId, speciesName: SpeciesId[speciesId] ?? null });
}

/** Whether this species still has an uncompleted dexsanity check. Drives the
 * "you should catch this" icon; see enemy-battle-info.ts's patch site. */
export function apNeedsCatch(speciesId: number): boolean {
  if (!state.connected || !state.dexsanity) {
    return false;
  }
  return state.pendingDexsanitySpecies.has(speciesId);
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

/**
 * Tag localStorage with the connected room's seed_name. The first time a
 * new or different seed_name shows up, flag that the next dexsanity scan
 * should silently baseline instead of reporting -- otherwise reconnecting an
 * existing save to a *different* multiworld (or resuming non-AP play) would
 * instantly fire every already-caught species as a check.
 *
 * Deliberately does nothing when seed_name is absent (older servers) or when
 * it matches what's already tagged -- both cases mean "keep reporting
 * normally".
 */
function establishBaselineIfNeeded(seedName: string | null): void {
  if (!seedName) {
    return;
  }
  let storedTag: string | null = null;
  try {
    storedTag = localStorage.getItem(SEED_TAG_KEY);
  } catch {
    return; // no localStorage access; nothing safe to do here
  }
  if (storedTag === seedName) {
    return;
  }
  needsBaselineSnapshot = true;
  try {
    localStorage.setItem(SEED_TAG_KEY, seedName);
  } catch {
    /* ignore */
  }
  try {
    console.info(
      `[Archipelago] New multiworld detected (${seedName}). Baselining existing catch ` +
        "history on this save -- only new catches from here on will send checks.",
    );
  } catch {
    /* ignore */
  }
}

function handleMessage(msg: Record<string, any>): void {
  switch (msg.cmd) {
    case "State": {
      state.connected = Boolean(msg.connected);
      state.slot = msg.slot ?? null;
      state.seedName = msg.seed_name ?? null;
      state.goalWave = Number(msg.goal_wave ?? 200);
      state.dexsanity = Boolean(msg.dexsanity);
      state.progressiveLevelCap = Boolean(msg.progressive_level_cap);
      state.deathLink = Boolean(msg.death_link);
      state.unlocked = new Set<number>((msg.unlocked_species ?? []).map(Number));
      state.allStarters = new Set<number>((msg.all_starter_species ?? []).map(Number));
      state.dexsanitySpecies = new Set<number>(
        Object.keys(msg.dexsanity_species ?? {}).map(Number),
      );
      state.pendingDexsanitySpecies = new Set<number>(
        (msg.pending_dexsanity_species ?? []).map(Number),
      );
      state.levelCapCount = Number(msg.level_cap_count ?? 0);
      state.levelCapTiers = (msg.level_cap_tiers ?? []).map(Number);

      establishBaselineIfNeeded(state.seedName);
      // A fresh state push may reveal checks we never reported (e.g. the
      // client restarted); clear the cache so the next poll re-reports (or
      // re-baselines, if establishBaselineIfNeeded just flagged that).
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
 * Grant or lock every species the gate manages, every tick. No-ops entirely
 * when the gate isn't active (Dexsanity off, or no AP session) -- see
 * gateActive.
 *
 * Grant: OR in the baseline "usable starter" bits, never subtracting from
 * whatever the game already recorded through real play. IVs are set to
 * 15/15/15/15/15/15 -- matching vanilla's own defaultStarterSpecies bootstrap
 * -- but only if they're still the untouched all-zero state, so a species
 * that was legitimately caught with rolled IVs before being granted keeps
 * those instead of being overwritten.
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
  if (!gateActive()) {
    return;
  }
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
      if (Array.isArray(dexEntry.ivs) && dexEntry.ivs.every((iv: number) => Number(iv) === 0)) {
        dexEntry.ivs = [...GRANT_IVS];
      }
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
 * on. Left untouched -- returns the vanilla wave-based value -- when the
 * option is off, when the caller explicitly asked to ignore the cap (this is
 * how Rare Candy already bypasses it in vanilla), or before AP connects.
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
    if (ignoreLevelCap || !state.connected || !state.progressiveLevelCap || state.levelCapTiers.length === 0) {
      return vanilla;
    }
    const tier = Math.min(state.levelCapCount, state.levelCapTiers.length - 1);
    return Math.min(vanilla, state.levelCapTiers[tier]);
  };
  s.__apLevelCapPatched = true;
}

/**
 * Register a small canvas-drawn "still needs catching" icon texture, so
 * enemy-battle-info.ts's patch has something to show without this project
 * needing to ship a new art asset through the build. Idempotent; safe to
 * call every poll tick.
 */
function ensureNeedsCatchTexture(s: any): void {
  try {
    if (!s?.textures || s.textures.exists(AP_CHECK_TEXTURE_KEY)) {
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    ctx.fillStyle = "#3ddc55";
    ctx.beginPath();
    ctx.arc(8, 8, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(4.5, 8.5);
    ctx.lineTo(7, 11);
    ctx.lineTo(11.5, 4.5);
    ctx.stroke();
    s.textures.addCanvas(AP_CHECK_TEXTURE_KEY, canvas);
  } catch {
    /* devtools/headless contexts without a real canvas; icon just won't show */
  }
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
  ensureNeedsCatchTexture(s);

  // ── Dexsanity ────────────────────────────────────────────────────────────
  if (state.dexsanity) {
    try {
      const caught = collectCaughtSpecies(s.gameData);
      if (needsBaselineSnapshot) {
        lastReportedCaught = caught;
        needsBaselineSnapshot = false;
      } else {
        for (const speciesId of caught) {
          if (!lastReportedCaught.has(speciesId)) {
            send({ cmd: "Catch", speciesId });
          }
        }
        lastReportedCaught = caught;
      }
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
      needsCatch: apNeedsCatch,
      resync: () => send({ cmd: "Sync" }),
    };
  } catch {
    /* ignore */
  }
}

start();
