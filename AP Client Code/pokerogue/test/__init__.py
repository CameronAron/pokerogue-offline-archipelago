"""Generation tests for the PokeRogue apworld."""

from test.bases import WorldTestBase

from ..Items import ITEM_NAME_TO_ID, PROGRESSIVE_LEVEL_CAP_ITEM
from ..Locations import LOCATION_NAME_TO_ID
from ..Species import STARTER_SPECIES


class PokeRogueTestBase(WorldTestBase):
    game = "PokeRogue"
    player: int = 1


class TestDefaults(PokeRogueTestBase):
    """Default options: dexsanity on, wave 200 goal."""

    options = {}

    def test_pool_balance(self) -> None:
        """Every location must have exactly one item to fill it."""
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(
            len(self.multiworld.itempool),
            len(locations),
            "item pool size must match unfilled location count",
        )

    def test_full_species_catalog_used(self) -> None:
        """Dexsanity on always uses every species -- no pool-size tuning."""
        self.assertEqual(len(self.world.species_pool), len(STARTER_SPECIES))
        self.assertEqual(len(self.world.starting_species), 3)

    def test_starting_species_precollected(self) -> None:
        precollected = {
            item.name for item in self.multiworld.precollected_items[self.player]
        }
        for species in self.world.starting_species:
            self.assertIn(f"{species.display} Unlock", precollected)

    def test_victory_event_exists(self) -> None:
        victory = self.multiworld.get_location("Classic Mode Victory", self.player)
        self.assertIsNone(victory.address, "victory must be an event, not a check")
        self.assertEqual(victory.item.name, "Victory")

    def test_completion_requires_victory(self) -> None:
        state = self.multiworld.get_all_state(False)
        self.assertTrue(self.multiworld.completion_condition[self.player](state))

    def test_goal_wave_not_a_location(self) -> None:
        """The goal wave is the completion event, so it must not also be a check."""
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Wave 200 Cleared", names)
        self.assertIn("Wave 190 Cleared", names)

    def test_all_species_have_dexsanity(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for species in self.world.species_pool:
            self.assertIn(f"Catch {species.display}", names)

    def test_no_progressive_level_cap(self) -> None:
        """Progressive Level Cap only exists when dexsanity is off."""
        names = {item.name for item in self.multiworld.itempool}
        self.assertNotIn(PROGRESSIVE_LEVEL_CAP_ITEM, names)

    def test_single_flat_region(self) -> None:
        """Everything should be immediately reachable -- no wave-ordering gate."""
        empty_state = self.multiworld.state
        for loc in self.multiworld.get_locations(self.player):
            self.assertTrue(
                loc.access_rule(empty_state), f"{loc.name} should have no access rule"
            )


class TestDexsanityOff(PokeRogueTestBase):
    """Dexsanity off: fixed roster, Progressive Level Cap fills wave checks."""

    options = {"dexsanity": False, "starting_species": 3, "wave_check_interval": 10}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_no_dexsanity_locations(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse(
            [n for n in names if n.startswith("Catch ")],
            "dexsanity locations must not exist when the option is off",
        )

    def test_roster_is_fixed_to_starting_species(self) -> None:
        self.assertEqual(len(self.world.species_pool), 0)
        self.assertEqual(len(self.world.starting_species), 3)

    def test_every_wave_check_is_progressive_level_cap(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        cap_count = names.count(PROGRESSIVE_LEVEL_CAP_ITEM)
        # 10..190 in steps of 10, exclusive of the goal wave itself.
        self.assertEqual(cap_count, 19)
        self.assertEqual(len(names), 19, "no filler needed -- counts should match exactly")

    def test_slot_data_exposes_level_cap_tiers(self) -> None:
        data = self.world.fill_slot_data()
        self.assertEqual(len(data["level_cap_tiers"]), 20)
        self.assertEqual(data["level_cap_tiers"][0], 10)
        self.assertEqual(data["level_cap_tiers"][-1], 200)
        self.assertIsNotNone(data["progressive_level_cap_item"])


class TestDexsanityOffShortGoal(PokeRogueTestBase):
    options = {"dexsanity": False, "goal_wave": 50, "wave_check_interval": 5}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_cap_items_match_wave_checks(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        # 5,10,...,45 -- exclusive of goal wave 50.
        self.assertEqual(names.count(PROGRESSIVE_LEVEL_CAP_ITEM), 9)


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


class TestMinimalStartingSpecies(PokeRogueTestBase):
    """Smallest legal configuration must still generate."""

    options = {"starting_species": 1, "dexsanity": False, "wave_check_interval": 25, "goal_wave": 50}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_one_starting_species(self) -> None:
        self.assertEqual(len(self.world.starting_species), 1)


class TestMaxStartingSpecies(PokeRogueTestBase):
    options = {"starting_species": 6}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_six_starting_species(self) -> None:
        self.assertEqual(len(self.world.starting_species), 6)


class TestDataIntegrity(PokeRogueTestBase):
    options = {}

    def test_unique_item_ids(self) -> None:
        self.assertEqual(
            len(ITEM_NAME_TO_ID), len(set(ITEM_NAME_TO_ID.values())), "duplicate item ids"
        )

    def test_unique_location_ids(self) -> None:
        self.assertEqual(
            len(LOCATION_NAME_TO_ID),
            len(set(LOCATION_NAME_TO_ID.values())),
            "duplicate location ids",
        )

    def test_unique_species_names(self) -> None:
        displays = [s.display for s in STARTER_SPECIES]
        self.assertEqual(len(displays), len(set(displays)), "duplicate species display names")

    def test_slot_data_shape(self) -> None:
        data = self.world.fill_slot_data()
        for key in (
            "goal_wave",
            "dexsanity",
            "dexsanity_species",
            "species_items",
            "all_starter_species",
            "pool_species",
            "starting_species",
            "wave_locations",
            "progressive_level_cap_item",
            "level_cap_tiers",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["goal_wave"], 200)
        self.assertEqual(len(data["pool_species"]), len(STARTER_SPECIES))
        self.assertEqual(len(data["dexsanity_species"]), len(STARTER_SPECIES))
        self.assertEqual(len(data["all_starter_species"]), len(STARTER_SPECIES))
        # dexsanity on -> no progressive level cap this seed
        self.assertIsNone(data["progressive_level_cap_item"])
        self.assertEqual(data["level_cap_tiers"], [])
