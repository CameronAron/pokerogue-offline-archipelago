#!/usr/bin/env python3
"""Extract PokeRogue's biome graph and per-biome species pools, and compute
how deep into a Classic run each species first becomes reachable.

This is research/prototype tooling for a wave-depth-aware refinement of
dexsanity_exclude_above_cost -- see the iteration notes for the reasoning.
Not wired into the apworld yet.

What this reads
----------------
Each file in src/data/balance/biomes/*.ts declares two things as plain,
non-randomized data:

  const biomeLinks: BiomeLinks = [BiomeId.CAVE, [BiomeId.SPACE, 2], ...];
  const pokemonPool: BiomePokemonPools = { [BiomePoolTier.COMMON]: { ... } };

`biomeLinks` is the branching graph the game itself walks in
src/init/init-biome-depths.ts (traverseBiome) to compute a [depth, chance]
pair per biome, starting from Town at depth 0. That function is otherwise
deterministic -- the one random call it makes only decides which biome the
END loop connects back to for post-200 content, which is out of scope here
and simply not simulated; END itself is still assigned a depth (one past the
deepest biome found), matching what the real function does before that call.

`pokemonPool` lists every species that can appear in that biome, across all
rarity tiers and times of day. This script does not preserve which tier or
time of day a species came from -- v1 only cares about "reachable at all",
not "how likely within the biome".

Wave correspondence
--------------------
Biome transitions happen every 10 waves (see select-biome-phase.ts:
`nextWaveIndex % 10 === 1`), so biome depth D first becomes reachable at
wave (D * 10 + 1). A species whose shallowest biome is at depth 2 is
therefore first reachable around wave 21, not before.

Usage
-----
    python tools/research_biome_depth.py /path/to/pokerogue-src
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_biome_id_enum(src: Path) -> dict[str, int]:
    text = (src / "enums" / "biome-id.ts").read_text(encoding="utf8")
    body = text[text.index("{") + 1 : text.rindex("}")]
    ids: dict[str, int] = {}
    for line in body.splitlines():
        match = re.match(r"\s*([A-Z0-9_]+):\s*(\d+),?", line)
        if match:
            ids[match.group(1)] = int(match.group(2))
    return ids


def parse_biome_file(path: Path, name_to_id: dict[str, int]) -> tuple[list[tuple[int, int]], set[int]]:
    """Return (links as [(target_id, chance), ...], species ids in the pool)."""
    text = path.read_text(encoding="utf8")

    links: list[tuple[int, int]] = []
    links_match = re.search(r"const biomeLinks:\s*BiomeLinks\s*=\s*(\[[\s\S]*?\]);", text)
    if links_match:
        raw = links_match.group(1)
        # Entries are either `BiomeId.NAME` or `[BiomeId.NAME, chance]`.
        for entry_match in re.finditer(
            r"\[\s*BiomeId\.([A-Z0-9_]+)\s*,\s*(\d+)\s*\]|BiomeId\.([A-Z0-9_]+)", raw
        ):
            if entry_match.group(1):
                name, chance = entry_match.group(1), int(entry_match.group(2))
            else:
                name, chance = entry_match.group(3), 1
            if name in name_to_id:
                links.append((name_to_id[name], chance))

    species_ids: set[int] = set()
    pool_match = re.search(r"const pokemonPool:\s*BiomePokemonPools\s*=\s*({[\s\S]*?});\n\n", text)
    pool_text = pool_match.group(1) if pool_match else text
    for species_match in re.finditer(r"SpeciesId\.([A-Z0-9_]+)", pool_text):
        species_ids.add(species_match.group(1))  # resolved to numeric ids by the caller

    return links, species_ids


def compute_biome_depths(
    graph: dict[int, list[tuple[int, int]]], town_id: int, end_id: int
) -> dict[int, tuple[int, int]]:
    """Reimplementation of initBiomeDepths()/traverseBiome() in Python.

    depths[biome] = (depth, chance). Chance is the branch weight the game
    used to decide which candidate depth "wins" when a biome is reachable
    via more than one path -- lower chance (rarer branch) or, at equal
    chance, greater depth, loses to the alternative, exactly mirroring the
    original's tie-break condition.
    """
    depths: dict[int, tuple[int, int]] = {town_id: (0, 1)}

    def traverse(biome_id: int, depth: int) -> None:
        if biome_id == end_id:
            return  # the real function re-rolls a random biome here; out of scope
        for target, chance in graph.get(biome_id, []):
            existing = depths.get(target)
            if (
                existing is None
                or chance < existing[1]
                or (depth < existing[0] and chance == existing[1])
            ):
                depths[target] = (depth + 1, chance)
                traverse(target, depth + 1)

    traverse(town_id, 0)
    if end_id not in depths:
        max_depth = max((d for d, _ in depths.values()), default=0)
        depths[end_id] = (max_depth + 1, 1)
    return depths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()

    src = args.checkout / "src"
    name_to_id = parse_biome_id_enum(src)
    id_to_name = {v: k for k, v in name_to_id.items()}

    graph: dict[int, list[tuple[int, int]]] = {}
    species_by_biome_name: dict[int, set[str]] = {}

    biome_dir = src / "data" / "balance" / "biomes"
    for path in sorted(biome_dir.glob("*.ts")):
        stem_name = path.stem.upper().replace("-", "_")
        biome_id = name_to_id.get(stem_name)
        if biome_id is None:
            print(f"WARNING: no BiomeId for file {path.name} (tried {stem_name})", file=sys.stderr)
            continue
        links, species_names = parse_biome_file(path, name_to_id)
        graph[biome_id] = links
        species_by_biome_name[biome_id] = species_names

    town_id = name_to_id["TOWN"]
    end_id = name_to_id["END"]
    depths = compute_biome_depths(graph, town_id, end_id)

    print(f"Parsed {len(graph)} biomes.")
    print(f"{'Biome':20s} {'Depth':>6s} {'Wave~':>6s} {'Species':>8s}")
    for biome_id in sorted(depths, key=lambda b: depths[b][0]):
        depth, _chance = depths[biome_id]
        wave = depth * 10 + 1
        name = id_to_name.get(biome_id, f"#{biome_id}")
        count = len(species_by_biome_name.get(biome_id, ()))
        print(f"{name:20s} {depth:6d} {wave:6d} {count:8d}")

    # Species -> shallowest depth across every biome it can appear in.
    species_shallowest: dict[str, int] = {}
    for biome_id, names in species_by_biome_name.items():
        depth = depths.get(biome_id, (99, 1))[0]
        for name in names:
            if name not in species_shallowest or depth < species_shallowest[name]:
                species_shallowest[name] = depth

    print(f"\nSpecies with biome data: {len(species_shallowest)}")
    never_seen = [n for n in species_shallowest if n not in {}]  # placeholder for cross-check
    deepest = sorted(species_shallowest.items(), key=lambda kv: -kv[1])[:15]
    print("Deepest-only species (sample):")
    for name, depth in deepest:
        print(f"  {name:20s} depth {depth:3d}  wave~{depth * 10 + 1}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
