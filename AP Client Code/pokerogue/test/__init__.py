"""Generation tests for the PokeRogue apworld."""

from test.bases import WorldTestBase

from ..Items import ITEM_NAME_TO_ID
from ..Locations import LOCATION_NAME_TO_ID
from ..Species import STARTER_SPECIES


class PokeRogueTestBase(WorldTestBase):
    game = "PokeRogue"
    player: int = 1


class TestDefaults(PokeRogueTestBase):
    """Default options: dexsanity on, 120 species, wave 200 goal."""

    options = {}

    def test_pool_balance(self) -> None:
        """Every location must have exactly one item to fill it."""
        locations = self.multiworld.get_unfilled_locations(self.player)
        # itempool is shared, but in a solo test it is all ours.
        self.assertEqual(
            len(self.multiworld.itempool),
            len(locations),
            "item pool size must match unfilled location count",
        )

    def test_species_pool_size(self) -> None:
        self.assertEqual(len(self.world.species_pool), 120)
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

    def test_all_pool_species_have_dexsanity(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for species in self.world.species_pool:
            self.assertIn(f"Catch {species.display}", names)


class TestDexsanityOff(PokeRogueTestBase):
    """With dexsanity off the species pool must clamp to the wave checks."""

    options = {
        "dexsanity": False,
        "species_pool_size": 120,
        "wave_check_interval": 10,
    }

    def test_pool_clamped(self) -> None:
        # 19 wave checks (10..190), minus a filler reserve, plus 3 precollected.
        self.assertLessEqual(len(self.world.species_pool), 20)
        self.assertGreaterEqual(len(self.world.species_pool), 6)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_no_dexsanity_locations(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse(
            [n for n in names if n.startswith("Catch ")],
            "dexsanity locations must not exist when the option is off",
        )


class TestShortGoal(PokeRogueTestBase):
    options = {"goal_wave": 50, "wave_check_interval": 5, "species_pool_size": 30}

    def test_wave_locations_stop_before_goal(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Wave 45 Cleared", names)
        self.assertNotIn("Wave 50 Cleared", names)
        self.assertNotIn("Wave 55 Cleared", names)

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))


class TestMinimalPool(PokeRogueTestBase):
    """Smallest legal configuration must still generate."""

    options = {
        "species_pool_size": 6,
        "starting_species": 6,
        "wave_check_interval": 25,
        "goal_wave": 50,
    }

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_everything_precollected_is_playable(self) -> None:
        self.assertEqual(len(self.world.starting_species), 6)


class TestMaximalPool(PokeRogueTestBase):
    """Every starter in the game at once."""

    options = {"species_pool_size": len(STARTER_SPECIES), "dexsanity": True}

    def test_pool_balance(self) -> None:
        locations = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(locations))

    def test_full_roster(self) -> None:
        self.assertEqual(len(self.world.species_pool), len(STARTER_SPECIES))


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
            "pool_species",
            "starting_species",
            "wave_locations",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["goal_wave"], 200)
        self.assertEqual(len(data["pool_species"]), 120)
        # every pooled species must be resolvable to a location
        self.assertEqual(len(data["dexsanity_species"]), 120)
