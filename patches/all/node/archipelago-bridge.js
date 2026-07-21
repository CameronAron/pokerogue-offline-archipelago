#!/usr/bin/env node
/**
 * Patch: archipelago-bridge.js
 *
 * Wires Archipelago multiworld support into the PokeRogue build.
 *
 * Design intent: keep the patched surface as small as possible. Almost all of
 * the integration lives in a single new module (ap-bridge.ts) that *observes*
 * `globalScene` on a timer, because polling public state survives upstream
 * churn far better than a dozen regex anchors would. Only three things cannot
 * be done by observation, and those are the only three anchors below:
 *
 *   1. src/system/archipelago/ap-bridge.ts  (new file)
 *        The bridge itself. Copied verbatim from new-files/.
 *
 *   2. src/main.ts
 *        A side-effect import so the bridge starts with the game.
 *
 *   3. src/ui/handlers/starter-select-ui-handler.ts
 *        Block selecting a species whose AP unlock item has not arrived.
 *        This must be a real patch -- a poller cannot refuse an input.
 *
 *   4. src/phases/game-over-phase.ts
 *        Report a Classic-mode victory (the goal condition) and a run loss
 *        (for DeathLink). Patched rather than polled because the goal must be
 *        exact, and `sessionsWon` alone cannot distinguish this run from a
 *        previously imported save.
 *
 * When the Archipelago client is not running, `apIsSpeciesUnlocked()` returns
 * true for everything and the bridge sends nothing, so a patched build plays
 * exactly like an unpatched one. That property is worth preserving in any
 * future edits here.
 *
 * NOTE ON TESTING: anchors below were confirmed against pagefaultgames/pokerogue
 * `main` at v1.12.0.9. The apworld and its generation are covered by unit tests;
 * the in-game behaviour of this patch has NOT been verified in a real build yet.
 * Build once and sanity-check before shipping.
 *
 * Targets:
 *   pokerogue-src/src/system/archipelago/ap-bridge.ts        (created)
 *   pokerogue-src/src/main.ts
 *   pokerogue-src/src/ui/handlers/starter-select-ui-handler.ts
 *   pokerogue-src/src/phases/game-over-phase.ts
 */

const fs = require("fs");
const path = require("path");

function readFile(filePath) {
  if (!fs.existsSync(filePath)) {
    console.error(`ERROR: Could not find ${filePath}`);
    console.error("Make sure this script is run from the repo root and all submodules are initialised.");
    process.exit(1);
  }
  return fs.readFileSync(filePath, "utf8").replace(/\r\n/g, "\n");
}

function writeFile(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
  console.log(`  Written: ${filePath}`);
}

function requireAnchor(src, anchor, label) {
  if (!src.includes(anchor)) {
    console.error(`ERROR: Could not find anchor for "${label}".`);
    console.error("The upstream file may have changed. Manual inspection required.");
    process.exit(1);
  }
}

function requireMatch(src, pattern, label) {
  const match = src.match(pattern);
  if (!match) {
    console.error(`ERROR: Could not find anchor for "${label}".`);
    console.error("The upstream file may have changed. Manual inspection required.");
    process.exit(1);
  }
  return match;
}

// This patch script lives at patches/all/node/archipelago-bridge.js in the
// pkr-offline repo. The new source file it writes is checked into this
// same repo (under new-files/) so this script and its payload stay together.
const NEW_FILES_DIR = path.join(__dirname, "..", "..", "..", "new-files");

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 1: src/system/archipelago/ap-bridge.ts  (new file)
// ─────────────────────────────────────────────────────────────────────────────

const BRIDGE_PATH = path.join("pokerogue-src", "src", "system", "archipelago", "ap-bridge.ts");

if (fs.existsSync(BRIDGE_PATH)) {
  console.log("SKIP ap-bridge.ts — already exists");
} else {
  const src = fs.readFileSync(
    path.join(NEW_FILES_DIR, "src", "system", "archipelago", "ap-bridge.ts"),
    "utf8",
  );
  writeFile(BRIDGE_PATH, src);
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 2: src/main.ts  →  start the bridge with the game
// ─────────────────────────────────────────────────────────────────────────────

const MAIN_PATH = path.join("pokerogue-src", "src", "main.ts");
let mainSrc = readFile(MAIN_PATH);

if (mainSrc.includes("archipelago/ap-bridge")) {
  console.log("SKIP main.ts — bridge import already present");
} else {
  // Anchored on the i18n import so we land after the polyfills, which the
  // upstream file explicitly requires to be first.
  const ANCHOR = 'import "#app/i18n"; // Initializes i18n on import';
  requireAnchor(mainSrc, ANCHOR, "i18n side-effect import in main.ts");
  mainSrc = mainSrc.replace(
    ANCHOR,
    `${ANCHOR}\nimport "#app/system/archipelago/ap-bridge"; // archipelago: starts the multiworld bridge`,
  );
  writeFile(MAIN_PATH, mainSrc);
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 3: starter-select-ui-handler.ts  →  gate locked species
// ─────────────────────────────────────────────────────────────────────────────

const STARTER_PATH = path.join(
  "pokerogue-src",
  "src",
  "ui",
  "handlers",
  "starter-select-ui-handler.ts",
);
let starterSrc = readFile(STARTER_PATH);

if (starterSrc.includes("apIsSpeciesUnlocked")) {
  console.log("SKIP starter-select-ui-handler.ts — gate already present");
} else {
  // 3a: import the gate helper.
  const IMPORT_ANCHOR = requireMatch(
    starterSrc,
    /^import .*from "#app\/global-scene";$/m,
    "global-scene import in starter-select-ui-handler.ts",
  )[0];
  starterSrc = starterSrc.replace(
    IMPORT_ANCHOR,
    `${IMPORT_ANCHOR}\nimport { apIsSpeciesUnlocked } from "#app/system/archipelago/ap-bridge";`,
  );

  // 3b: refuse the ACTION button for a species we have not been sent.
  //
  // Upstream reads:
  //     if (!this.speciesStarterDexEntry?.caughtAttr) {
  //       error = true;
  //     } else if (this.starterSpecies.length <= 6) {
  //
  // `caughtAttr` is the vanilla "have you ever caught this" check; we AND in
  // the Archipelago unlock so an uncaught *or* un-granted species is refused.
  const GATE_PATTERN =
    /([ \t]*)if \(!this\.speciesStarterDexEntry\?\.caughtAttr\) \{\n([ \t]*)error = true;\n/;
  const gateMatch = requireMatch(
    starterSrc,
    GATE_PATTERN,
    "starter ACTION caughtAttr guard",
  );

  const indent = gateMatch[1];
  const innerIndent = gateMatch[2];
  const replacement =
    `${indent}// archipelago: a species is selectable only if it has been caught AND its\n` +
    `${indent}// unlock item has been received. Outside a multiworld this is a no-op.\n` +
    `${indent}if (!this.speciesStarterDexEntry?.caughtAttr || !apIsSpeciesUnlocked(this.lastSpecies.speciesId)) {\n` +
    `${innerIndent}error = true;\n`;

  starterSrc = starterSrc.replace(gateMatch[0], replacement);
  writeFile(STARTER_PATH, starterSrc);
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 4: game-over-phase.ts  →  report victory / defeat
// ─────────────────────────────────────────────────────────────────────────────

const GAMEOVER_PATH = path.join("pokerogue-src", "src", "phases", "game-over-phase.ts");
let gameOverSrc = readFile(GAMEOVER_PATH);

if (gameOverSrc.includes("apNotifyVictory")) {
  console.log("SKIP game-over-phase.ts — victory notify already present");
} else {
  // 4a: import the notifiers.
  const IMPORT_ANCHOR = requireMatch(
    gameOverSrc,
    /^import .*from "#app\/global-scene";$/m,
    "global-scene import in game-over-phase.ts",
  )[0];
  gameOverSrc = gameOverSrc.replace(
    IMPORT_ANCHOR,
    `${IMPORT_ANCHOR}\nimport { apNotifyDefeat, apNotifyVictory } from "#app/system/archipelago/ap-bridge";`,
  );

  // 4b: hook the Classic victory bookkeeping. `sessionsWon++` runs exactly
  // once per won Classic run, inside `if (this.isVictory && isClassic)`.
  const WIN_PATTERN = /([ \t]*)globalScene\.gameData\.gameStats\.sessionsWon\+\+;/;
  const winMatch = requireMatch(gameOverSrc, WIN_PATTERN, "sessionsWon increment");
  const winIndent = winMatch[1];
  gameOverSrc = gameOverSrc.replace(
    winMatch[0],
    `${winMatch[0]}\n` +
      `${winIndent}// archipelago: this is the goal condition for the Classic run.\n` +
      `${winIndent}apNotifyVictory(globalScene.currentBattle?.waveIndex ?? 200);`,
  );

  // 4c: report a run-ending loss for DeathLink. Anchored on the fade duration
  // line, which runs for both outcomes, so we branch on isVictory ourselves.
  const FADE_PATTERN = /([ \t]*)const fadeDuration = this\.isVictory \? 10000 : 5000;/;
  const fadeMatch = requireMatch(gameOverSrc, FADE_PATTERN, "game over fade duration");
  const fadeIndent = fadeMatch[1];
  gameOverSrc = gameOverSrc.replace(
    fadeMatch[0],
    `${fadeIndent}// archipelago: a lost run is the closest thing PokeRogue has to a death.\n` +
      `${fadeIndent}if (!this.isVictory) {\n` +
      `${fadeIndent}  apNotifyDefeat(globalScene.currentBattle?.waveIndex ?? 0);\n` +
      `${fadeIndent}}\n` +
      `${fadeMatch[0]}`,
  );

  writeFile(GAMEOVER_PATH, gameOverSrc);
}

console.log("Archipelago bridge applied successfully.");
