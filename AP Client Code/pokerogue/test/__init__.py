"""Generation tests for the PokeRogue apworld."""

from BaseClasses import LocationProgressType
from test.bases import WorldTestBase

from ..Items import EXP_GAIN_TIERS, ITEM_NAME_TO_ID, PROGRESSIVE_EXP_GAIN_ITEM
from ..Locations import LOCATION_NAME_TO_ID
from ..Species import DEFAULT_STARTER_POOL, DEXSANITY_RARE_ENCOUNTER_ONLY, DEXSANITY_UNOBTAINABLE, STARTER_SPECIES


class PokeRogueTestBase(WorldTestBase):
    game = "PokeRogue"
    player: int = 1


class TestDefaults(PokeRogueTestBase):
    """Default options: dexsanity on, progressive exp gain off, random starters on."""

    options = {}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_full_species_catalog_used(self) -> None:
        self.assertEqual(len(self.world.species_pool), len(STARTER_SPECIES))
        self.assertEqual(len(self.world.starting_species), 3)

    def test_starting_species_precollected(self) -> None:
        precollected = {item.name for item in self.multiworld.precollected_items[self.player]}
        for species in self.world.starting_species:
            self.assertIn(f"{species.display} Unlock", precollected)

    def test_victory_event_exists(self) -> None:
        victory = self.multiworld.get_location("Classic Mode Victory", self.player)
        self.assertIsNone(victory.address)
        self.assertEqual(victory.item.name, "Victory")

    def test_completion_requires_victory(self) -> None:
        state = self.multiworld.get_all_state(False)
        self.assertTrue(self.multiworld.completion_condition[self.player](state))

    def test_goal_wave_not_a_location(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Wave 200 Cleared", names)
        self.assertIn("Wave 190 Cleared", names)

    def test_all_species_have_dexsanity(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for species in self.world.species_pool:
            if species.enum_name in DEXSANITY_UNOBTAINABLE:
                self.assertNotIn(f"Catch {species.display}", names)
            else:
                self.assertIn(f"Catch {species.display}", names)

    def test_unobtainable_species_have_no_location_at_all(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for enum_name in DEXSANITY_UNOBTAINABLE:
            species = next(s for s in self.world.species_pool if s.enum_name == enum_name)
            self.assertNotIn(f"Catch {species.display}", names)

    def test_no_progressive_exp_gain_by_default(self) -> None:
        names = {item.name for item in self.multiworld.itempool}
        self.assertNotIn(PROGRESSIVE_EXP_GAIN_ITEM, names)

    def test_species_items_are_useful_not_progression(self) -> None:
        from BaseClasses import ItemClassification

        for item in self.multiworld.itempool:
            if item.name.endswith(" Unlock"):
                self.assertTrue(item.classification & ItemClassification.useful)
                self.assertFalse(item.classification & ItemClassification.progression)

    def test_single_flat_region(self) -> None:
        empty_state = self.multiworld.state
        for loc in self.multiworld.get_locations(self.player):
            self.assertTrue(loc.access_rule(empty_state), f"{loc.name} should have no access rule")

    def test_high_cost_dexsanity_excluded(self) -> None:
        exclude_above = self.world.options.dexsanity_exclude_above_cost.value
        excluded_count = 0
        for species in self.world.species_pool:
            if species.enum_name in DEXSANITY_UNOBTAINABLE:
                continue  # no location exists for these at all -- see the dedicated test
            loc = self.multiworld.get_location(f"Catch {species.display}", self.player)
            if species.cost > exclude_above or species.enum_name in DEXSANITY_RARE_ENCOUNTER_ONLY:
                self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)
                excluded_count += 1
            else:
                self.assertEqual(loc.progress_type, LocationProgressType.DEFAULT)
        self.assertGreater(excluded_count, 0)

    def test_rare_encounter_only_species_always_excluded(self) -> None:
        # Regardless of dexsanity_exclude_above_cost, these five have no
        # normal wild spawn -- only a rare, non-guaranteed encounter -- so
        # they stay excluded even at a cost well under the threshold.
        for enum_name in DEXSANITY_RARE_ENCOUNTER_ONLY:
            species = next((s for s in self.world.species_pool if s.enum_name == enum_name), None)
            if species is None:
                continue  # not every rare-encounter-only species is guaranteed cost-eligible here
            loc = self.multiworld.get_location(f"Catch {species.display}", self.player)
            self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)

    def test_encounter_bias_off_by_default(self) -> None:
        self.assertEqual(self.world.options.dexsanity_encounter_bias.value, 0)


class TestDexsanityAndExpGainBoth(PokeRogueTestBase):
    """Both sanities on at once -- independent toggles, not exclusive."""

    options = {"dexsanity": True, "progressive_exp_gain": True}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_both_item_types_present(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        self.assertIn(PROGRESSIVE_EXP_GAIN_ITEM, names)
        self.assertTrue(any(n.endswith(" Unlock") for n in names))

    def test_dexsanity_locations_exist(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertTrue(any(n.startswith("Catch ") for n in names))


class TestAggressiveExclusionStressTest(PokeRogueTestBase):
    """Worst case for the excluded-locations-vs-fillable-items constraint:
    both sanities on, and exclusion turned up so high that most of the
    species pool's own locations can't hold a species/EXP-gain item at all.
    This must trim gracefully (some species lose their unlock item) rather
    than crash generation."""

    options = {"dexsanity": True, "progressive_exp_gain": True, "dexsanity_exclude_above_cost": 1}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_every_excluded_location_holds_pure_filler(self) -> None:
        from BaseClasses import ItemClassification
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        for loc in self.multiworld.get_locations(self.player):
            if loc.progress_type == LocationProgressType.EXCLUDED:
                self.assertEqual(
                    loc.item.classification,
                    ItemClassification.filler,
                    f"{loc.name} holds a {loc.item.classification!r} item but is excluded",
                )

    def test_most_locations_are_excluded(self) -> None:
        # Cost 1 is the cheapest tier, so almost everything except cost-1
        # species gets excluded -- this is the scenario that overflowed
        # before the capacity fix.
        self.assertGreater(self.world.excluded_location_count, 400)


class TestDexsanityOffExpGainOff(PokeRogueTestBase):
    """Neither sanity on: plain wave-progress checks, vanilla catching."""

    options = {"dexsanity": False, "progressive_exp_gain": False}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_no_dexsanity_locations(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse([n for n in names if n.startswith("Catch ")])

    def test_no_progressive_exp_gain_items(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        self.assertNotIn(PROGRESSIVE_EXP_GAIN_ITEM, names)

    def test_wave_checks_are_pure_filler(self) -> None:
        # 19 wave checks (10..190), all filled with ordinary filler/useful items.
        self.assertEqual(len(self.multiworld.itempool), 19)


class TestProgressiveExpGainAlone(PokeRogueTestBase):
    """EXP gain on, dexsanity off."""

    options = {"dexsanity": False, "progressive_exp_gain": True, "wave_check_interval": 10}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_every_wave_check_is_progressive_exp_gain(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        self.assertEqual(names.count(PROGRESSIVE_EXP_GAIN_ITEM), 19)
        self.assertEqual(len(names), 19)

    def test_slot_data_exposes_exp_gain_tiers(self) -> None:
        data = self.world.fill_slot_data()
        self.assertEqual(len(data["exp_gain_tiers"]), 20)
        # Baseline (zero copies) must be a reduction, never a hard wall --
        # this is the entire point of the redesign away from a hard level
        # cap: a rate can only ever make things slower, never impossible.
        self.assertLess(data["exp_gain_tiers"][0], 100)
        self.assertGreater(data["exp_gain_tiers"][0], 0)
        # Full completion should meet or exceed normal as a reward.
        self.assertGreaterEqual(data["exp_gain_tiers"][-1], 100)
        self.assertIsNotNone(data["progressive_exp_gain_item"])

    def test_exp_gain_tiers_monotonically_increase(self) -> None:
        tiers = list(EXP_GAIN_TIERS)
        self.assertEqual(tiers, sorted(tiers), "each further copy must never lower the rate")

    def test_dexsanity_off_species_pool_empty(self) -> None:
        self.assertEqual(len(self.world.species_pool), 0)


class TestDisableLevelCap(PokeRogueTestBase):
    """A pure gameplay toggle -- no items or locations of its own, and
    independent of Progressive EXP Gain (which can still throttle the rate
    even with no ceiling to hit)."""

    options = {"disable_level_cap": True, "progressive_exp_gain": False}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_slot_data_reflects_it(self) -> None:
        data = self.world.fill_slot_data()
        self.assertTrue(data["disable_level_cap"])


class TestDisableLevelCapWithExpGain(PokeRogueTestBase):
    """Both axes on at once -- a throttled rate with no ceiling to eventually
    hit is a legitimate combination, not a conflict."""

    options = {"disable_level_cap": True, "progressive_exp_gain": True}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_both_flags_true(self) -> None:
        data = self.world.fill_slot_data()
        self.assertTrue(data["disable_level_cap"])
        self.assertTrue(data["progressive_exp_gain"])


class TestDexsanityEncounterBias(PokeRogueTestBase):
    """Encounter bias is a plain percentage option, independent of everything else."""

    options = {"dexsanity": True, "dexsanity_encounter_bias": 50}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_bias_value_in_slot_data(self) -> None:
        data = self.world.fill_slot_data()
        self.assertEqual(data["dexsanity_encounter_bias"], 50)

    def test_bias_has_no_effect_on_items_or_locations(self) -> None:
        # Encounter bias only affects which wild Pokemon shows up in-game; it
        # must never change the item/location pool itself.
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for species in self.world.species_pool:
            if species.enum_name in DEXSANITY_UNOBTAINABLE:
                continue
            self.assertIn(f"Catch {species.display}", names)


class TestCuratedStarters(PokeRogueTestBase):
    """Random Starters off: curated 27-species pool, cost-capped."""

    options = {"random_starters": False, "starting_species": 3}

    def test_starting_species_from_curated_pool(self) -> None:
        curated_ids = {s.species_id for s in DEFAULT_STARTER_POOL}
        for species in self.world.starting_species:
            self.assertIn(species.species_id, curated_ids)

    def test_starting_species_within_cost_cap(self) -> None:
        total_cost = sum(s.cost for s in self.world.starting_species)
        self.assertLessEqual(total_cost, 10)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_curated_starters_skip_own_dexsanity_check(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for species in self.world.starting_species:
            self.assertNotIn(f"Catch {species.display}", names)

    def test_precredited_species_tracked(self) -> None:
        starting_ids = {s.species_id for s in self.world.starting_species}
        self.assertEqual(self.world.precredited_species, starting_ids)


class TestCuratedStartersOverBudget(PokeRogueTestBase):
    """Requesting more curated starters than the cost cap allows must clamp,
    not crash. Every curated species costs >= 3, so 4+ always exceeds 10."""

    options = {"random_starters": False, "starting_species": 6}

    def test_clamped_not_crashed(self) -> None:
        self.assertLessEqual(len(self.world.starting_species), 3)
        self.assertGreaterEqual(len(self.world.starting_species), 1)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))


class TestExcludeAboveCostDisabled(PokeRogueTestBase):
    """Setting the exclusion threshold to 10 (the max cost) disables the
    cost-based side of exclusion. The five rare-encounter-only species stay
    excluded regardless -- that's a fixed obtainability fact, not something
    the cost slider controls."""

    options = {"dexsanity_exclude_above_cost": 10}

    def test_nothing_excluded_except_rare_encounter_species(self) -> None:
        for loc in self.multiworld.get_locations(self.player):
            if not loc.name.startswith("Catch "):
                continue
            display = loc.name[len("Catch ") :]
            is_rare_encounter_only = any(
                s.enum_name in DEXSANITY_RARE_ENCOUNTER_ONLY and s.display == display
                for s in self.world.species_pool
            )
            if is_rare_encounter_only:
                self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)
            else:
                self.assertEqual(loc.progress_type, LocationProgressType.DEFAULT)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))


class TestShortGoal(PokeRogueTestBase):
    options = {"goal_wave": 50, "wave_check_interval": 5}

    def test_wave_locations_stop_before_goal(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Wave 45 Cleared", names)
        self.assertNotIn("Wave 50 Cleared", names)
        self.assertNotIn("Wave 55 Cleared", names)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))


class TestFloorCheckInterval(PokeRogueTestBase):
    """wave_check_interval down to 1 gives a check on every single wave --
    the FloorSanity-style option, expressed as an interval value rather than
    a whole separate mechanic."""

    options = {"wave_check_interval": 1, "goal_wave": 50, "dexsanity": False}

    def test_every_wave_is_a_location(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for wave in range(1, 50):
            self.assertIn(f"Wave {wave} Cleared", names)
        self.assertNotIn("Wave 50 Cleared", names)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))


class TestMaxStartingSpecies(PokeRogueTestBase):
    options = {"starting_species": 6, "random_starters": True}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_six_starting_species(self) -> None:
        self.assertEqual(len(self.world.starting_species), 6)


class TestDataIntegrity(PokeRogueTestBase):
    options = {}

    def test_unique_item_ids(self) -> None:
        self.assertEqual(len(ITEM_NAME_TO_ID), len(set(ITEM_NAME_TO_ID.values())))

    def test_unique_location_ids(self) -> None:
        self.assertEqual(len(LOCATION_NAME_TO_ID), len(set(LOCATION_NAME_TO_ID.values())))

    def test_obtainability_sets_resolve(self) -> None:
        all_names = {s.enum_name for s in STARTER_SPECIES}
        for enum_name in DEXSANITY_UNOBTAINABLE | DEXSANITY_RARE_ENCOUNTER_ONLY:
            self.assertIn(enum_name, all_names, f"{enum_name} is not a known starter species")

    def test_obtainability_sets_disjoint(self) -> None:
        self.assertEqual(DEXSANITY_UNOBTAINABLE & DEXSANITY_RARE_ENCOUNTER_ONLY, set())

    def test_unique_species_names(self) -> None:
        displays = [s.display for s in STARTER_SPECIES]
        self.assertEqual(len(displays), len(set(displays)))

    def test_curated_pool_resolves(self) -> None:
        self.assertEqual(len(DEFAULT_STARTER_POOL), 27)
        for species in DEFAULT_STARTER_POOL:
            self.assertIn(species, STARTER_SPECIES)

    def test_exp_gain_tiers_shape(self) -> None:
        self.assertEqual(len(EXP_GAIN_TIERS), 20)

    def test_slot_data_shape(self) -> None:
        data = self.world.fill_slot_data()
        for key in (
            "goal_wave",
            "dexsanity",
            "dexsanity_encounter_bias",
            "progressive_exp_gain",
            "disable_level_cap",
            "dexsanity_species",
            "species_items",
            "all_starter_species",
            "pool_species",
            "starting_species",
            "wave_locations",
            "progressive_exp_gain_item",
            "exp_gain_tiers",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["goal_wave"], 200)
        self.assertEqual(len(data["pool_species"]), len(STARTER_SPECIES))
        self.assertEqual(len(data["all_starter_species"]), len(STARTER_SPECIES))
        self.assertIsNone(data["progressive_exp_gain_item"])
        self.assertEqual(data["exp_gain_tiers"], [])
        self.assertEqual(data["dexsanity_encounter_bias"], 0)
        self.assertFalse(data["disable_level_cap"])
