/**
 * Archipelago bridge for PokeRogue Offline.
 *
 * Runs inside the Electron renderer (or a browser userscript build) and talks
 * to the Archipelago PokeRogue client over a localhost WebSocket. The client
 * owns all authoritative state; this module only:
 *
 *   1. observes the live game and reports events (catches, waves, victory), and
 *   2. enforces species availability and (in two independent modes) EXP gain
 *      rate and encounter selection locally, using the state the client sends.
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
 * species lock, EXP gain rate, encounter selection, dexsanity detection -- is
 * this module driving or wrapping the game's own data structures and methods
 * directly.
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
 * vanilla, and the only Archipelago mechanics left are Progressive EXP Gain
 * and Dexsanity Encounter Bias (each its own independent toggle -- see
 * installExpGainOverride and installEncounterBiasOverride).
 *
 * Progressive EXP Gain deliberately throttles a *rate*, not a hard level cap.
 * An earlier design clamped `getMaxExpLevel` outright, which meant a seed
 * where the multiworld hadn't yet sent enough copies could become physically
 * unwinnable -- no amount of play could get past a wave whose difficulty
 * required a level the cap refused to allow. A rate multiplier can only ever
 * make leveling slower, never impossible: a skilled or patient player can
 * always out-grind a low rate. See installExpGainOverride.
 *
 * Dexsanity Encounter Bias substitutes a still-needed species into a wild or
 * boss encounter, but only ever *after* the game's own seeded RNG has fully
 * resolved a natural roll -- it never consumes an additional seeded random
 * call itself, so it cannot shift the deterministic sequence every other
 * random event in a run depends on. See installEncounterBiasOverride for the
 * detailed reasoning.
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
 * handled by permanently excluding, per seed_name, whatever was already
 * caught the first time that seed connects. This is persisted to its own
 * localStorage record (not just held in memory), specifically so it survives
 * every later State push -- an earlier version of this fix relied on an
 * in-memory cache that gets legitimately cleared on every ordinary item
 * receipt, which meant the protection only lasted until the next unrelated
 * game event. See establishBaselineIfNeeded.
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
import { speciesDataRegistry } from "#app/global-species-data-registry";

const BRIDGE_VERSION = "0.4.0";
const DEFAULT_PORT = 17777;
const POLL_INTERVAL_MS = 1000;
const RECONNECT_DELAY_MS = 3000;
const BASELINE_KEY = "ap_dexsanity_baselines";
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
  /** 0-100. Chance to substitute a still-needed species into an eligible
   * wild/boss encounter. 0 means the mechanism never fires. */
  dexsanityEncounterBias: number;
  progressiveExpGain: boolean;
  /** Removes Classic mode's own wave-based level cap entirely. Independent
   * of progressiveExpGain -- one controls how fast EXP comes in, this
   * controls how high a level it's ever allowed to reach. */
  disableLevelCap: boolean;
  deathLink: boolean;
  /** Species the player may currently use. Sole source of truth for the gate. */
  unlocked: Set<number>;
  /** Every species the gate manages at all. Empty/unused when dexsanity is off. */
  allStarters: Set<number>;
  /** Species that have a dexsanity check attached (empty when dexsanity is off). */
  dexsanitySpecies: Set<number>;
  /** Species with a dexsanity check that hasn't fired yet -- drives the
   * "still needs catching" icon and encounter bias substitution candidates. */
  pendingDexsanitySpecies: Set<number>;
  /** Copies of Progressive EXP Gain received so far. */
  expGainCount: number;
  /** EXP gain rate as a percentage of normal, tier 1 (baseline) first. Empty
   * when the option is off. */
  expGainTiers: number[];
}

const state: ApState = {
  connected: false,
  slot: null,
  seedName: null,
  goalWave: 200,
  dexsanity: true,
  dexsanityEncounterBias: 0,
  progressiveExpGain: false,
  disableLevelCap: false,
  deathLink: false,
  unlocked: new Set<number>(),
  allStarters: new Set<number>(),
  dexsanitySpecies: new Set<number>(),
  pendingDexsanitySpecies: new Set<number>(),
  expGainCount: 0,
  expGainTiers: [],
};

let socket: WebSocket | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** Last catch set we reported, so we only send on change. Purely a
 * spam-reduction cache -- resetting it is always safe now, since permanent
 * "never report this" exclusion lives in `excludedBaseline` instead (see
 * establishBaselineIfNeeded's doc comment for why that split matters). */
let lastReportedCaught = new Set<number>();
let lastReportedWave = -1;
/** Set when a seed with no persisted baseline yet is seen; consumed on the
 * next poll to compute and permanently persist that baseline. */
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

/**
 * A species and every one of its prevolutions, walking the chain the exact
 * same way `GameData.setPokemonSpeciesCaught`'s own `checkPrevolution` does
 * (`speciesDataRegistry.getPrevolution`, repeated until it returns null) --
 * all the way to the true base form, not just the nearest registered
 * starter. This matters because that same recursive walk is what credits a
 * catch: catching a wild Raichu increments `caughtCount` for Raichu, then
 * Pikachu, then Pichu in turn, since Pichu and Pikachu are each their own
 * independently-registered starter. Checking unlock/pending status against
 * only the encountered species' own ID -- which is what an earlier version
 * of this file did -- can never match anything for an already-evolved wild
 * encounter, since evolved-only forms never appear in `species_items` or
 * `dexsanity_species` at all. That meant a wild Charizard, Raichu, or any
 * other already-evolved encounter was being rejected from the party
 * unconditionally, regardless of whether Charmander or Pikachu was
 * unlocked -- not a cosmetic gap, a real gate over-block.
 */
function apEvolutionChain(speciesId: number): number[] {
  const chain = [speciesId];
  let current = speciesId;
  for (let i = 0; i < 16; i++) {
    // 16 is generously above any real PokeRogue evolution chain length;
    // purely a guard against an unexpected cycle turning this into an
    // infinite loop, not a realistic depth limit.
    let prevolution: number | null = null;
    try {
      prevolution = speciesDataRegistry.getPrevolution(current);
    } catch {
      break;
    }
    if (prevolution == null || chain.includes(prevolution)) {
      break;
    }
    chain.push(prevolution);
    current = prevolution;
  }
  return chain;
}

/** Whether the player is currently allowed to use this species -- checking
 * the species itself and every prevolution in its chain (see
 * apEvolutionChain), so an already-evolved wild encounter correctly counts
 * as unlocked whenever any ancestor in its line has been granted. Read-only;
 * the gate itself is enforced by writing dexData directly (see below) and by
 * apCanAddToParty for in-run catches, so nothing needs to call this to block
 * a selection. Exposed for any future UI that wants to read it. */
export function apIsSpeciesUnlocked(speciesId: number): boolean {
  if (!gateActive()) {
    return true;
  }
  return apEvolutionChain(speciesId).some(id => state.unlocked.has(id));
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

/** Whether this species, or any prevolution in its chain, still has an
 * uncompleted dexsanity check (see apEvolutionChain for why the chain, not
 * just the encountered species' own ID, has to be checked). Drives the
 * "you should catch this" icon; see enemy-battle-info.ts's patch site. */
export function apNeedsCatch(speciesId: number): boolean {
  if (!state.connected || !state.dexsanity) {
    return false;
  }
  return apEvolutionChain(speciesId).some(id => state.pendingDexsanitySpecies.has(id));
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
 * Species excluded from dexsanity reporting for the *current* seed, because
 * they were already caught before this seed was ever connected to. Loaded
 * from (and kept in sync with) a persistent, per-seed localStorage record --
 * deliberately NOT just an in-memory cache. An earlier version of this fix
 * used a transient cache (`lastReportedCaught`) as the only thing standing
 * between "already caught" and "reported as a fresh catch", and that cache
 * gets legitimately cleared by resetReportCache() on every subsequent State
 * push (which happens on every ordinary item receipt, not just at connect).
 * The result: baseline protection silently evaporated the moment any
 * unrelated item arrived, and every pre-existing catch fired for real on the
 * next poll. Persisting the exclusion list itself, rather than relying on a
 * cache that's supposed to never get cleared at the wrong time, closes that
 * hole for good -- there is no code path left that both wants to clear
 * lastReportedCaught for legitimate reasons AND accidentally un-excludes a
 * baselined species, because the two are no longer the same variable.
 */
let excludedBaseline = new Set<number>();

function loadBaselineMap(): Record<string, number[]> {
  try {
    const raw = localStorage.getItem(BASELINE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveBaselineMap(map: Record<string, number[]>): void {
  try {
    localStorage.setItem(BASELINE_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

/**
 * Ensure `excludedBaseline` reflects the right permanent exclusion set for
 * whichever seed is currently connected. Three cases:
 *
 *   - No seed_name at all (older servers, or a momentary gap before it's
 *     available): leave `excludedBaseline` exactly as it already is, rather
 *     than clearing it. A transient null observation must never be able to
 *     silently drop protection that was already correctly established --
 *     the only way to lose an established baseline is a genuinely different
 *     seed_name showing up.
 *   - A seed we've never seen on this save: flag that the next poll should
 *     snapshot current catches and persist them as this seed's baseline.
 *   - A seed we've already tagged before (including "the same seed as last
 *     State push", which is the overwhelmingly common case -- this runs on
 *     every State message): load its already-persisted baseline back into
 *     `excludedBaseline` so it survives regardless of what else changes.
 *
 * Every branch logs what it did. This exists to be observable from the
 * game's own devtools console: if reported catch history isn't being
 * excluded as expected, these lines show directly whether seed_name is
 * reaching the bridge at all, and whether it's being recognised as new or
 * already-known -- narrowing down which half of the mechanism to look at
 * without needing to add anything just to investigate it.
 */
function establishBaselineIfNeeded(seedName: string | null): void {
  if (!seedName) {
    logBaseline(`no seed_name yet (${excludedBaseline.size} species currently excluded, unchanged)`);
    return;
  }

  const map = loadBaselineMap();
  const existing = map[seedName];

  if (existing) {
    excludedBaseline = new Set<number>(existing.map(Number));
    logBaseline(`reusing existing baseline for ${seedName} (${excludedBaseline.size} species excluded)`);
    return;
  }

  needsBaselineSnapshot = true;
  logBaseline(`new seed ${seedName} -- baselining current catch history on the next poll`);
}

/** Force a fresh baseline for whichever seed is currently connected, even if
 * one was already established. Exposed via the client's `/rebaseline`
 * command as a manual escape hatch -- useful if a save's history needs
 * re-excluding without a full data wipe (Settings -> Offline -> Clear All
 * Data), or while narrowing down a baseline-related report. */
export function apForceRebaseline(): void {
  needsBaselineSnapshot = true;
  logBaseline("forced rebaseline requested (/rebaseline)");
}

function logBaseline(message: string): void {
  try {
    console.info(`[Archipelago] baseline: ${message}`);
  } catch {
    /* ignore */
  }
}

/** Called from poll() once, right after a fresh baseline snapshot is taken. */
function persistBaseline(seedName: string | null, caught: Set<number>): void {
  excludedBaseline = new Set<number>(caught);
  logBaseline(`snapshot taken -- ${caught.size} species excluded going forward`);
  if (!seedName) {
    return;
  }
  const map = loadBaselineMap();
  map[seedName] = Array.from(caught);
  saveBaselineMap(map);
}

function handleMessage(msg: Record<string, any>): void {
  switch (msg.cmd) {
    case "State": {
      state.connected = Boolean(msg.connected);
      state.slot = msg.slot ?? null;
      state.seedName = msg.seed_name ?? null;
      state.goalWave = Number(msg.goal_wave ?? 200);
      state.dexsanity = Boolean(msg.dexsanity);
      state.dexsanityEncounterBias = Number(msg.dexsanity_encounter_bias ?? 0);
      state.progressiveExpGain = Boolean(msg.progressive_exp_gain);
      state.disableLevelCap = Boolean(msg.disable_level_cap);
      state.deathLink = Boolean(msg.death_link);
      state.unlocked = new Set<number>((msg.unlocked_species ?? []).map(Number));
      state.allStarters = new Set<number>((msg.all_starter_species ?? []).map(Number));
      state.dexsanitySpecies = new Set<number>(
        Object.keys(msg.dexsanity_species ?? {}).map(Number),
      );
      state.pendingDexsanitySpecies = new Set<number>(
        (msg.pending_dexsanity_species ?? []).map(Number),
      );
      state.expGainCount = Number(msg.exp_gain_count ?? 0);
      state.expGainTiers = (msg.exp_gain_tiers ?? []).map(Number);

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

    case "Rebaseline": {
      apForceRebaseline();
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
 * Current EXP gain multiplier, as a plain fraction of normal (1.0 = 100%).
 * Tier 0 (no copies received) is the throttled baseline; each further copy
 * climbs a tier, eventually exceeding 100% at full completion. Returns 1.0
 * (no effect) whenever the option is off or before AP connects.
 */
function currentExpGainMultiplier(): number {
  if (!state.connected || !state.progressiveExpGain || state.expGainTiers.length === 0) {
    return 1;
  }
  const tier = Math.min(state.expGainCount, state.expGainTiers.length - 1);
  return state.expGainTiers[tier] / 100;
}

/**
 * Patch a single Pokemon instance's `addExp` to scale incoming EXP by the
 * current AP tier multiplier. Idempotent via a marker property; safe to call
 * on the same instance repeatedly.
 *
 * Deliberately an *instance*-level patch, not a prototype patch on the
 * `Pokemon` class. Patching the prototype would need importing the `Pokemon`
 * class into this module -- but `field/pokemon.ts` already imports *from*
 * this module for the party-add gate (apCanAddToParty), and importing it
 * back here would create a circular import between the two files. Instance
 * patching sidesteps that entirely: this function is exported so the
 * patched `addToParty` can call it the instant a Pokemon actually joins the
 * party (closing the gap before the next poll tick would otherwise catch
 * it), and installExpGainOverride below also sweeps the whole party every
 * poll tick as a backstop.
 *
 * Exp Charm, Lucky Egg, and other vanilla EXP boosters (`ExpBoosterModifier`)
 * resolve before `addExp` is ever called (see `phases/exp-phase.ts`), so
 * this multiplier applies on top of whatever they already gave -- vanilla
 * boosters are never wasted, they just get scaled further by wherever the AP
 * tier sits. Rare Candy is unaffected either way, since it increments
 * `.level` directly and never calls `addExp` at all.
 */
export function apPatchExpGain(pokemon: any): void {
  if (!pokemon || pokemon.__apExpGainPatched || typeof pokemon.addExp !== "function") {
    return;
  }
  const original: (exp: number, ignoreLevelCap?: boolean) => void = pokemon.addExp.bind(pokemon);
  pokemon.addExp = (exp: number, ignoreLevelCap = false): void => {
    original(exp * currentExpGainMultiplier(), ignoreLevelCap);
  };
  pokemon.__apExpGainPatched = true;
}

/** Sweep the live party every poll tick, patching any member not already
 * covered. A backstop for apPatchExpGain -- most of the time a party member
 * is already patched by the time this runs, since the party-add patch calls
 * apPatchExpGain immediately, but this covers anything that slipped through
 * (e.g. a party loaded from a session resume). */
function installExpGainOverride(s: any): void {
  if (!state.connected || !state.progressiveExpGain) {
    return;
  }
  const party = typeof s.getPlayerParty === "function" ? s.getPlayerParty() : null;
  if (!Array.isArray(party)) {
    return;
  }
  for (const pokemon of party) {
    apPatchExpGain(pokemon);
  }
}

/**
 * Install (once) a wrapper around `globalScene.getMaxExpLevel` that removes
 * the wave-based cap entirely when Disable Level Cap is on, returning a very
 * high ceiling regardless of wave. Left untouched -- returns the vanilla
 * value -- whenever the option is off, before AP connects, or when the
 * caller explicitly asked to ignore the cap already (Rare Candy's own
 * bypass; passing through here changes nothing about how that already
 * works).
 *
 * A completely separate axis from Progressive EXP Gain: that hook scales how
 * much EXP arrives per battle (installExpGainOverride, on `Pokemon.addExp`);
 * this one only affects the ceiling `addExp` is allowed to level up to. They
 * compose without needing to know about each other -- a low gain rate still
 * applies normally even with no ceiling at all, it just takes longer to
 * reach any given level.
 *
 * Patches the live scene instance, not the source -- the same pattern this
 * project previously used for the old hard-capped level design, before that
 * was replaced by the EXP-rate mechanic. Idempotent via a marker property;
 * self-reinstalls if the scene is ever recreated.
 */
function installLevelCapDisableOverride(s: any): void {
  if (s.__apLevelCapDisablePatched || typeof s.getMaxExpLevel !== "function") {
    return;
  }
  const original: (ignoreLevelCap?: boolean) => number = s.getMaxExpLevel.bind(s);
  s.getMaxExpLevel = (ignoreLevelCap = false): number => {
    if (ignoreLevelCap || !state.connected || !state.disableLevelCap) {
      return original(ignoreLevelCap);
    }
    return 9999;
  };
  s.__apLevelCapDisablePatched = true;
}

/**
 * Find which of `arena.pokemonPool`'s tier arrays contains this species ID.
 * Deliberately searches by value across whatever tiers exist rather than
 * indexing by a specific `BiomePoolTier` enum value -- that avoids this
 * module depending on the enum's exact numeric layout at all, on top of
 * never needing to select a tier itself (which would mean replicating the
 * game's own seeded tier roll, exactly the risk this design avoids).
 * Returns null if not found in any tier -- callers should treat that as
 * "can't confidently match rarity" and skip biasing that encounter, rather
 * than guess.
 */
function findMatchingTierPool(arena: any, speciesId: number): number[] | null {
  const pools = arena?.pokemonPool;
  if (!pools) {
    return null;
  }
  for (const tierPool of Object.values(pools)) {
    if (Array.isArray(tierPool) && (tierPool as number[]).includes(speciesId)) {
      return tierPool as number[];
    }
  }
  return null;
}

/**
 * Install (once) a wrapper around `globalScene.arena.randomSpecies` that may
 * substitute a still-needed dexsanity species into an eligible wild or boss
 * encounter. This is the mechanism described at length in the module doc
 * comment; the short version is repeated here since it's the part most
 * worth re-reading before touching this function.
 *
 * Safety property: this NEVER consumes an additional call to the game's
 * seeded RNG. The original `randomSpecies` is called exactly once and
 * allowed to fully resolve -- including its own internal retries for empty
 * tiers or level-incompatible legendaries, which recurse through
 * `this.randomSpecies(...)` and therefore back through this very wrapper;
 * substitution logic only runs on the outermost call (`attempt === 0`), so
 * those internal retries pass through untouched. Only once a final species
 * has been fully resolved -- including PokeRogue's own level-appropriate
 * evolution stage adjustment -- does this function decide, using
 * `Math.random` (never the seeded generator), whether to swap it for a
 * same-tier species still needed for dexsanity. `getWildSpeciesForLevel`
 * (used to re-level the substitute exactly as vanilla would have) is a pure
 * function with no RNG calls of its own, confirmed by reading its body, so
 * calling it an extra time for the substitute costs nothing.
 *
 * Substitution only ever happens within the SAME tier array (searched by
 * membership, not by replaying the tier roll -- see findMatchingTierPool)
 * the natural roll's pre-adjustment species came from, so it can never make
 * an encounter easier or harder than the wave already intends -- only more
 * likely to be useful. If that tier can't be confidently identified (the
 * natural pick isn't found in any tier array, which can happen for some
 * evolution-stage edge cases), this skips biasing that single encounter
 * rather than guess at an unverified rarity match.
 *
 * `arena` (and therefore this wrapper) is recreated on some scene
 * transitions, so this self-reinstalls via a marker property checked every
 * poll tick, the same pattern as the old level-cap override used.
 */
function installEncounterBiasOverride(s: any): void {
  const arena = s?.arena;
  if (!arena || arena.__apEncounterBiasPatched || typeof arena.randomSpecies !== "function") {
    return;
  }
  const original: (
    waveIndex: number,
    level: number,
    attempt?: number,
    luckValue?: number,
    isBoss?: boolean,
  ) => any = arena.randomSpecies.bind(arena);

  arena.randomSpecies = (
    waveIndex: number,
    level: number,
    attempt = 0,
    luckValue = 0,
    isBoss?: boolean,
  ): any => {
    const natural = original(waveIndex, level, attempt, luckValue, isBoss);

    // Only ever decide on the outermost call. Vanilla's own internal retries
    // (empty tier, incompatible legendary level) recurse back through this
    // wrapper at attempt > 0; let those resolve exactly as vanilla intends.
    if (attempt > 0 || !natural) {
      return natural;
    }
    if (
      !state.connected ||
      !state.dexsanity ||
      state.dexsanityEncounterBias <= 0 ||
      state.pendingDexsanitySpecies.size === 0
    ) {
      return natural;
    }

    const naturalId: number = natural.speciesId;
    const naturalChain = apEvolutionChain(naturalId);
    if (naturalChain.some(id => state.pendingDexsanitySpecies.has(id))) {
      return natural; // already a useful roll (itself or an ancestor); nothing to improve
    }

    // Tier pools store base/catchable forms, but `natural` may already be a
    // leveled-up evolution (`getWildSpeciesForLevel` runs before this point).
    // Try the encountered species first, then fall back through its
    // prevolution chain, so a high-level wild Charizard can still match
    // Charmander's tier instead of being skipped for not being found
    // directly in any pool array.
    let tierPool: number[] | null = null;
    for (const id of naturalChain) {
      tierPool = findMatchingTierPool(arena, id);
      if (tierPool) {
        break;
      }
    }
    if (!tierPool) {
      return natural; // can't confidently match rarity; leave this one alone
    }

    const candidates = tierPool.filter(
      id => id !== naturalId && state.pendingDexsanitySpecies.has(id),
    );
    if (candidates.length === 0) {
      return natural; // nothing pending in this rarity tier to swap toward
    }

    // Independent, non-seeded decision -- never the game's own generator.
    if (Math.random() * 100 >= state.dexsanityEncounterBias) {
      return natural;
    }

    try {
      const chosenId = candidates[Math.floor(Math.random() * candidates.length)];
      let substitute = speciesDataRegistry.getSpecies(chosenId);
      const leveledId = substitute.getWildSpeciesForLevel(
        level,
        true,
        isBoss ?? false,
        globalScene.gameMode,
      );
      if (leveledId !== substitute.speciesId) {
        substitute = speciesDataRegistry.getSpecies(leveledId);
      }
      try {
        console.info(
          `[Archipelago] Encounter bias: swapped ${SpeciesId[naturalId] ?? naturalId} for ` +
            `${SpeciesId[substitute.speciesId] ?? substitute.speciesId} (still needed for dexsanity).`,
        );
      } catch {
        /* logging failure is never worth losing the substitution over */
      }
      return substitute;
    } catch {
      return natural; // any lookup failure just falls back to the vanilla roll
    }
  };

  arena.__apEncounterBiasPatched = true;
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

  installExpGainOverride(s);
  installLevelCapDisableOverride(s);
  installEncounterBiasOverride(s);
  ensureNeedsCatchTexture(s);

  // ── Dexsanity ────────────────────────────────────────────────────────────
  if (state.dexsanity) {
    try {
      const caught = collectCaughtSpecies(s.gameData);
      if (needsBaselineSnapshot) {
        // Persist immediately -- this is the permanent, never-reported set
        // for this seed from here on, regardless of how many further State
        // pushes arrive (see establishBaselineIfNeeded's doc comment).
        persistBaseline(state.seedName, caught);
        needsBaselineSnapshot = false;
        lastReportedCaught = caught;
      } else {
        for (const speciesId of caught) {
          if (excludedBaseline.has(speciesId)) {
            continue;
          }
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
