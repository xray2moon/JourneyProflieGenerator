import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Source.infra_data_manager import InfrastructureParser
from testing.infrastructure_description_generator import (
    InfrastructureDescriptionGenerator,
    InfrastructureGenerationConfig,
)


class TestInfrastructureDescriptionGenerator(unittest.TestCase):
    def test_generated_json_has_expected_top_level_shape(self):
        generator = InfrastructureDescriptionGenerator(seed="shape-test")
        data = generator.build()

        expected_keys = {
            "nodes",
            "tracks",
            "allocationSections",
            "platforms",
            "stoppingLocations",
            "speedConstraints",
            "stoppingLocationGroups",
            "segmentProfiles",
            "timingPoints",
            "virtualNodes",
            "virtualTracks",
            "blockSections",
            "dpsGroups",
        }
        self.assertEqual(set(data.keys()), expected_keys)
        self.assertGreaterEqual(len(data["nodes"]), 3)
        self.assertGreaterEqual(len(data["tracks"]), 2)
        self.assertGreaterEqual(len(data["timingPoints"]), 1)

    def test_parser_can_load_generated_dict(self):
        config = InfrastructureGenerationConfig(
            main_node_count=6,
            track_length_m=800.0,
            timing_points_per_direction=4,
            include_branch=True,
            include_virtual_tracks=True,
        )
        data = InfrastructureDescriptionGenerator(seed="parser-test").build(config)
        model = InfrastructureParser.parse_dict(data)

        self.assertGreaterEqual(len(model.nodes), config.main_node_count)
        self.assertGreaterEqual(len(model.tracks), config.main_node_count - 1)
        self.assertGreaterEqual(len(model.timing_points), 1)
        self.assertGreaterEqual(len(model.stopping_locations), 1)

    def test_write_json_and_parse_file_round_trip(self):
        generator = InfrastructureDescriptionGenerator(seed="file-roundtrip")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "synthetic_infrastructure.json")
            written_path = generator.write_json(out_path)

            with open(written_path, "r", encoding="utf-8") as f:
                reloaded = json.load(f)
            self.assertIn("nodes", reloaded)
            self.assertIn("tracks", reloaded)

            model = InfrastructureParser.parse_file(str(written_path))
            self.assertGreaterEqual(len(model.nodes), 3)
            self.assertGreaterEqual(len(model.tracks), 2)

    def test_default_output_paths_increment_from_zero(self):
        old_cwd = os.getcwd()
        tmpdir_obj = tempfile.TemporaryDirectory()
        try:
            os.chdir(tmpdir_obj.name)
            generator = InfrastructureDescriptionGenerator(seed="increment-test")
            first = generator.write_json()
            second = generator.write_json()

            self.assertEqual(first.name, "infrastructure_0.json")
            self.assertEqual(second.name, "infrastructure_1.json")
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
        finally:
            os.chdir(old_cwd)
            tmpdir_obj.cleanup()

    def test_no_seed_produces_different_infrastructures(self):
        data_a = InfrastructureDescriptionGenerator().build()
        data_b = InfrastructureDescriptionGenerator().build()
        self.assertNotEqual(data_a["nodes"][0]["id"], data_b["nodes"][0]["id"])

    def test_same_unseeded_instance_produces_different_builds(self):
        generator = InfrastructureDescriptionGenerator()
        data_a = generator.build()
        data_b = generator.build()
        self.assertNotEqual(data_a["nodes"][0]["id"], data_b["nodes"][0]["id"])


if __name__ == "__main__":
    unittest.main()
