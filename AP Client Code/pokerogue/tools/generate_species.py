#!/usr/bin/env python3
"""Regenerate Species.py from a PokeRogue source checkout.

PokeRogue's `main` branch adds and rebalances starters regularly, so the species
table in this apworld is generated rather than hand-maintained. Re-run this
whenever you rebuild the game against a newer upstream.

Usage:
    python tools/generate_species.py /path/to/pokerogue-src

The checkout only needs `src/` present; a sparse clone is enough:

    git clone --filter=blob:none --no-checkout --depth 1 \\
        https://github.com/pagefaultgames/pokerogue.git pokerogue-src
    cd pokerogue-src
    git sparse-checkout init --cone && git sparse-checkout set src && git checkout

What it reads
-------------
* ``src/data/balance/species/generation-*.ts`` -- every species declaring a
  ``starterCost`` is a selectable starter, which is the universe of both the
  unlock items and the dexsanity locations.
* ``src/enums/species-id.ts`` -- the numeric SpeciesId enum, including implicit
  increments, so the generated IDs match what the game reports at runtime.
* ``package.json`` -- recorded as SOURCE_GAME_VERSION for diagnostics.

Changing the ID of an existing species will invalidate in-progress multiworlds,
so review the diff before committing a regenerated table.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADER = '''"""
Auto-generated PokeRogue starter species table.

Generated from pagefaultgames/pokerogue @ {version} by parsing
src/data/balance/species/generation-*.ts for entries that declare a
`starterCost`, joined against the numeric SpeciesId enum in
src/enums/species-id.ts.

Do not hand-edit. Regenerate with tools/generate_species.py when the
upstream game version changes.
"""

from typing import NamedTuple


class SpeciesInfo(NamedTuple):
    """A single selectable starter species."""

    enum_name: str
    species_id: int
    cost: int
    generation: int
    display: str


#: Game version this table was generated from.
SOURCE_GAME_VERSION = "{version}"

STARTER_SPECIES: tuple[SpeciesInfo, ...] = (
'''

FOOTER = ''')

#: display name -> SpeciesInfo
BY_NAME: dict[str, SpeciesInfo] = {s.display: s for s in STARTER_SPECIES}
#: numeric SpeciesId -> SpeciesInfo
BY_ID: dict[int, SpeciesInfo] = {s.species_id: s for s in STARTER_SPECIES}

#: enum_name -> SpeciesInfo, for looking up the curated trio table below.
BY_ENUM_NAME: dict[str, SpeciesInfo] = {s.enum_name: s for s in STARTER_SPECIES}

#: The three starters PokeRogue's own "Fresh Start (Full Reset)" challenge
#: locks a player to per generation -- the same 27 species real accounts
#: start with. Used when the `random_starters` option is off. Hand-curated,
#: not derived from generation-*.ts -- verify all 27 names still resolve
#: against STARTER_SPECIES after a regeneration (a missing/renamed species
#: would raise a KeyError at import time, so this fails loudly rather than
#: silently).
DEFAULT_STARTER_TRIO_NAMES: dict[int, tuple[str, str, str]] = {
    1: ("BULBASAUR", "CHARMANDER", "SQUIRTLE"),
    2: ("CHIKORITA", "CYNDAQUIL", "TOTODILE"),
    3: ("TREECKO", "TORCHIC", "MUDKIP"),
    4: ("TURTWIG", "CHIMCHAR", "PIPLUP"),
    5: ("SNIVY", "TEPIG", "OSHAWOTT"),
    6: ("CHESPIN", "FENNEKIN", "FROAKIE"),
    7: ("ROWLET", "LITTEN", "POPPLIO"),
    8: ("GROOKEY", "SCORBUNNY", "SOBBLE"),
    9: ("SPRIGATITO", "FUECOCO", "QUAXLY"),
}

#: Flat tuple of all 27 curated species, resolved to SpeciesInfo.
DEFAULT_STARTER_POOL: tuple[SpeciesInfo, ...] = tuple(
    BY_ENUM_NAME[name] for names in DEFAULT_STARTER_TRIO_NAMES.values() for name in names
)
'''


def parse_species_enum(path: Path) -> dict[str, int]:
    """Parse a TypeScript enum, resolving implicit increments."""
    text = path.read_text(encoding="utf8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    body = text[text.index("{") + 1 : text.rindex("}")]

    ids: dict[str, int] = {}
    current = -1
    for raw in body.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if "=" in entry:
            name, value = entry.split("=", 1)
            name, value = name.strip(), value.strip()
            try:
                current = int(value, 0)
            except ValueError:
                # Aliases to other members (e.g. `FOO = BAR`) are skipped; they
                # are not distinct species.
                continue
        else:
            name = entry
            current += 1
        if re.fullmatch(r"[A-Z0-9_]+", name):
            ids[name] = current
    return ids


def parse_starters(src: Path) -> dict[str, tuple[int, int]]:
    """Return enum_name -> (starter_cost, generation)."""
    starters: dict[str, tuple[int, int]] = {}
    files = sorted((src / "data" / "balance" / "species").glob("generation-*.ts"))
    if not files:
        sys.exit(f"No generation-*.ts files found under {src / 'data' / 'balance' / 'species'}")

    for path in files:
        match = re.search(r"generation-(\d+)\.ts$", path.name)
        generation = int(match.group(1)) if match else 0
        text = path.read_text(encoding="utf8")
        # Each species block starts with `<gen>SpeciesData[SpeciesId.NAME] = {`.
        for block in re.split(r"SpeciesData\[SpeciesId\.", text)[1:]:
            name = block[: block.index("]")]
            cost = re.search(r"\bstarterCost:\s*(\d+)", block)
            if cost:
                starters[name] = (int(cost.group(1)), generation)
    return starters


def prettify(enum_name: str) -> str:
    return " ".join(part.capitalize() for part in enum_name.split("_"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="Path to a pokerogue source checkout")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "Species.py",
        help="Where to write Species.py",
    )
    args = parser.parse_args()

    src = args.checkout / "src"
    if not src.is_dir():
        return int(bool(sys.stderr.write(f"No src/ directory under {args.checkout}\n"))) or 1

    version = "unknown"
    package_json = args.checkout / "package.json"
    if package_json.is_file():
        try:
            version = json.loads(package_json.read_text(encoding="utf8")).get("version", "unknown")
        except (json.JSONDecodeError, OSError):
            pass

    ids = parse_species_enum(src / "enums" / "species-id.ts")
    starters = parse_starters(src)

    missing = sorted(name for name in starters if name not in ids)
    if missing:
        print(f"WARNING: {len(missing)} starters absent from SpeciesId enum: {missing[:5]}")

    rows = sorted(
        ((name, ids[name], cost, gen) for name, (cost, gen) in starters.items() if name in ids),
        key=lambda row: (row[3], row[1]),
    )

    # Display names must be unique; they are used as AP item/location names.
    seen: set[str] = set()
    entries = []
    for name, species_id, cost, gen in rows:
        display = prettify(name)
        if display in seen:
            display = f"{display} ({name})"
        seen.add(display)
        entries.append((name, species_id, cost, gen, display))

    lines = [HEADER.format(version=version)]
    for name, species_id, cost, gen, display in entries:
        lines.append(f'    SpeciesInfo("{name}", {species_id}, {cost}, {gen}, "{display}"),\n')
    lines.append(FOOTER)

    args.output.write_text("".join(lines), encoding="utf8")
    print(f"Wrote {args.output} with {len(entries)} starters (game version {version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
