#!/usr/bin/env node
/**
 * Patch: archipelago-bridge.js
 *
 * Wires Archipelago multiworld support into the PokeRogue build.
 *
 * Design intent: keep the patched surface as small as possible. Nearly all of
 * the integration lives in a single new module (ap-bridge.ts) that *observes*
 * and *drives* `globalScene` on a timer, because polling/writing public state
 * survives upstream churn far better than a pile of regex anchors would. Four
 * things cannot be done this way, and are the only real anchors below:
 *
 *   1. src/system/archipelago/ap-bridge.ts  (new file)
 *        The bridge itself. Copied verbatim from new-files/.
 *
 *   2. src/main.ts
 *        A side-effect import so the bridge starts with the game.
 *
 *   3. src/phases/game-over-phase.ts
 *        Report a Classic-mode victory (the goal condition) and a run loss
 *        (for DeathLink). Patched rather than polled because the goal must be
 *        exact, and `sessionsWon` alone cannot distinguish this run from a
 *        previously imported save.
 *
 *   4. src/field/pokemon.ts
 *        Refuse to add a caught Pokemon to the party if Dexsanity is on and
 *        its species hasn't been unlocked. This is the one thing polling
 *        cannot do -- the game has already decided to add the Pokemon by the
 *        time a poll tick could react, so the refusal has to happen inline.
 *        Also patches Progressive EXP Gain onto a newly-added party member
 *        the instant it joins (apPatchExpGain), rather than leaving that
 *        entirely to installExpGainOverride's once-a-second sweep.
 *
 *   5. src/ui/battle-info/enemy-battle-info.ts
 *        Add a second icon next to the existing "owned" pokeball icon, shown
 *        when a wild Pokemon still has an uncompleted dexsanity check. Purely
 *        a wild-encounter nameplate render call; there is no way to observe
 *        or influence that from outside without patching the render site.
 *
 * Earlier versions of this patch also touched starter-select-ui-handler.ts to
 * add a second species-selection gate. That turned out to be the wrong design
 * -- it stacked a redundant AP-only condition next to the game's own
 * `caughtAttr` check, instead of *driving* caughtAttr, so AP-granted species
 * were never actually marked caught (nothing could ever be selected) and
 * vanilla's free starter bootstrap was never locked out (those species stayed
 * selectable and fired their checks immediately on connect). The bridge now
 * grants/locks caughtAttr directly, so the game's own vanilla logic *is* the
 * enforcement, and starter select no longer needs to be patched at all.
 *
 * When the Archipelago client is not running, the bridge sends nothing and
 * touches no game data, so a patched build plays exactly like an unpatched
 * one. That property is worth preserving in any future edits here.
 *
 * NOTE ON TESTING: anchors below were confirmed against pagefaultgames/pokerogue
 * `main` at v1.12.0.9. The apworld and its generation are covered by unit tests,
 * and this patch has been applied to a real checkout and typechecked. The
 * in-game runtime behaviour has NOT been verified in a built exe yet -- sub-patch
 * 5 (the UI icon) in particular is the least-tested change in this iteration,
 * since its correctness (positioning, visibility timing) can't be confirmed
 * without actually running the game.
 *
 * Targets:
 *   pokerogue-src/src/system/archipelago/ap-bridge.ts        (created)
 *   pokerogue-src/src/main.ts
 *   pokerogue-src/src/phases/game-over-phase.ts
 *   pokerogue-src/src/field/pokemon.ts
 *   pokerogue-src/src/ui/battle-info/enemy-battle-info.ts
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
// Sub-patch 3: game-over-phase.ts  →  report victory / defeat
// ─────────────────────────────────────────────────────────────────────────────

const GAMEOVER_PATH = path.join("pokerogue-src", "src", "phases", "game-over-phase.ts");
let gameOverSrc = readFile(GAMEOVER_PATH);

if (gameOverSrc.includes("apNotifyVictory")) {
  console.log("SKIP game-over-phase.ts — victory notify already present");
} else {
  // 3a: import the notifiers.
  const IMPORT_ANCHOR = requireMatch(
    gameOverSrc,
    /^import .*from "#app\/global-scene";$/m,
    "global-scene import in game-over-phase.ts",
  )[0];
  gameOverSrc = gameOverSrc.replace(
    IMPORT_ANCHOR,
    `${IMPORT_ANCHOR}\nimport { apNotifyDefeat, apNotifyVictory } from "#app/system/archipelago/ap-bridge";`,
  );

  // 3b: hook the Classic victory bookkeeping. `sessionsWon++` runs exactly
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

  // 3c: report a run-ending loss for DeathLink. Anchored on the fade duration
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

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 4: field/pokemon.ts  →  refuse to add a locked catch to the party
// ─────────────────────────────────────────────────────────────────────────────

const POKEMON_PATH = path.join("pokerogue-src", "src", "field", "pokemon.ts");
let pokemonSrc = readFile(POKEMON_PATH);

if (pokemonSrc.includes("apCanAddToParty")) {
  console.log("SKIP field/pokemon.ts — party gate already present");
} else {
  // 4a: import the gate + notifier.
  const IMPORT_ANCHOR = requireMatch(
    pokemonSrc,
    /^import \{ globalScene \} from "#app\/global-scene";$/m,
    "global-scene import in field/pokemon.ts",
  )[0];
  pokemonSrc = pokemonSrc.replace(
    IMPORT_ANCHOR,
    `${IMPORT_ANCHOR}\nimport { apCanAddToParty, apNotifyLockedCatch, apPatchExpGain } from "#app/system/archipelago/ap-bridge";`,
  );

  // 4b: gate the actual party-add. When blocked, `ret` stays null exactly
  // like PokeRogue's own "party is already full" case already leaves it --
  // no new failure mode for callers, since every call site already handles
  // addToParty returning null.
  const PARTY_PATTERN =
    /([ \t]*)if \(party\.length < PLAYER_PARTY_MAX_SIZE\) \{\n/;
  const partyMatch = requireMatch(pokemonSrc, PARTY_PATTERN, "addToParty party-size guard");
  const indent = partyMatch[1];
  const replacement =
    `${indent}// archipelago: a species that hasn't been unlocked can't join the party,\n` +
    `${indent}// even though the catch itself (and the ball) still happens normally.\n` +
    `${indent}if (party.length < PLAYER_PARTY_MAX_SIZE && apCanAddToParty(this.species.speciesId)) {\n`;
  pokemonSrc = pokemonSrc.replace(partyMatch[0], replacement);

  // 4c: notify when a catch was blocked, anchored on the exact closing lines
  // of addToParty (verified unique against the real source).
  const TAIL_ANCHOR =
    "      globalScene.triggerPokemonFormChange(newPokemon, SpeciesFormChangeActiveTrigger, true);\n" +
    "    }\n" +
    "\n" +
    "    return ret;\n" +
    "  }\n";
  requireAnchor(pokemonSrc, TAIL_ANCHOR, "addToParty closing block");
  const TAIL_REPLACEMENT =
    "      globalScene.triggerPokemonFormChange(newPokemon, SpeciesFormChangeActiveTrigger, true);\n" +
    "    } else if (party.length < PLAYER_PARTY_MAX_SIZE) {\n" +
    "      // archipelago: distinguish \"locked\" from \"party full\" for the player,\n" +
    "      // surfaced in the Archipelago client's own log rather than in-game, to\n" +
    "      // avoid interfering with attempt-capture-phase's own UI sequencing.\n" +
    "      apNotifyLockedCatch(this.species.speciesId);\n" +
    "    }\n" +
    "\n" +
    "    return ret;\n" +
    "  }\n";
  pokemonSrc = pokemonSrc.replace(TAIL_ANCHOR, TAIL_REPLACEMENT);

  // 4d: patch Progressive EXP Gain onto a newly-added party member the
  // instant it joins, rather than waiting for the next poll tick to catch
  // it (installExpGainOverride's per-tick sweep is only a backstop).
  const RET_ANCHOR = "      ret = newPokemon;\n";
  requireAnchor(pokemonSrc, RET_ANCHOR, "addToParty ret assignment");
  pokemonSrc = pokemonSrc.replace(
    RET_ANCHOR,
    `${RET_ANCHOR}      // archipelago: apply the current EXP gain rate immediately, rather\n` +
      "      // than waiting for the next poll tick to notice this party member.\n" +
      "      apPatchExpGain(newPokemon);\n",
  );

  writeFile(POKEMON_PATH, pokemonSrc);
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-patch 5: enemy-battle-info.ts  →  "still needs catching" icon
// ─────────────────────────────────────────────────────────────────────────────

const ENEMY_INFO_PATH = path.join(
  "pokerogue-src",
  "src",
  "ui",
  "battle-info",
  "enemy-battle-info.ts",
);
let enemyInfoSrc = readFile(ENEMY_INFO_PATH);

if (enemyInfoSrc.includes("apNeedsCatch")) {
  console.log("SKIP enemy-battle-info.ts — needs-catch icon already present");
} else {
  // 5a: import the check.
  const IMPORT_ANCHOR = requireMatch(
    enemyInfoSrc,
    /^import \{ globalScene \} from "#app\/global-scene";$/m,
    "global-scene import in enemy-battle-info.ts",
  )[0];
  enemyInfoSrc = enemyInfoSrc.replace(
    IMPORT_ANCHOR,
    `${IMPORT_ANCHOR}\nimport { apNeedsCatch } from "#app/system/archipelago/ap-bridge";`,
  );

  // 5b: declare the new sprite field, next to the existing owned/ribbon ones.
  const FIELD_ANCHOR = requireMatch(
    enemyInfoSrc,
    /( {2}protected ownedIcon: Phaser\.GameObjects\.Sprite;\n)/,
    "ownedIcon field declaration",
  )[0];
  enemyInfoSrc = enemyInfoSrc.replace(
    FIELD_ANCHOR,
    `${FIELD_ANCHOR}  protected apNeedsCatchIcon: Phaser.GameObjects.Sprite;\n`,
  );

  // 5c: construct the sprite alongside championRibbon, positioned a full row
  // below the existing icons so it never overlaps ownedIcon or championRibbon
  // regardless of which combination of those is visible.
  const RIBBON_BLOCK_PATTERN =
    /( {4}this\.championRibbon = globalScene\.add\n[\s\S]*?setPositionRelative\(this\.nameText, 8, 11\.75\);\n)/;
  const ribbonMatch = requireMatch(enemyInfoSrc, RIBBON_BLOCK_PATTERN, "championRibbon construction");
  const newSpriteBlock =
    `${ribbonMatch[1]}\n` +
    `    // archipelago: shown when this species still has an uncompleted\n` +
    `    // dexsanity check. A full row below the existing badges so it never\n` +
    `    // collides with ownedIcon or championRibbon in any combination.\n` +
    `    this.apNeedsCatchIcon = globalScene.add\n` +
    `      .sprite(0, 0, "ap_needs_catch_icon")\n` +
    `      .setName("icon_ap_needs_catch")\n` +
    `      .setVisible(false)\n` +
    `      .setOrigin(0, 0)\n` +
    `      .setPositionRelative(this.nameText, 0, 19.75);\n`;
  enemyInfoSrc = enemyInfoSrc.replace(ribbonMatch[0], newSpriteBlock);

  // 5d: include it in the same addAt call as the other two badge icons.
  const ADDAT_PATTERN =
    /this\.addAt\(\[this\.ownedIcon, this\.championRibbon\], this\.getIndex\(this\.statsContainer\)\);/;
  const addAtMatch = requireMatch(enemyInfoSrc, ADDAT_PATTERN, "ownedIcon/championRibbon addAt call");
  enemyInfoSrc = enemyInfoSrc.replace(
    addAtMatch[0],
    "this.addAt([this.ownedIcon, this.championRibbon, this.apNeedsCatchIcon], this.getIndex(this.statsContainer));",
  );

  // 5e: set visibility in initInfo, right after the existing ownedIcon line.
  const OWNED_VISIBLE_PATTERN =
    /([ \t]*)this\.ownedIcon\.setVisible\(!!dexEntry\.caughtAttr\);\n/;
  const ownedMatch = requireMatch(enemyInfoSrc, OWNED_VISIBLE_PATTERN, "ownedIcon.setVisible call");
  const visIndent = ownedMatch[1];
  enemyInfoSrc = enemyInfoSrc.replace(
    ownedMatch[0],
    `${ownedMatch[0]}${visIndent}this.apNeedsCatchIcon.setVisible(apNeedsCatch(pokemon.species.speciesId));\n`,
  );

  writeFile(ENEMY_INFO_PATH, enemyInfoSrc);
}

console.log("Archipelago bridge applied successfully.");


