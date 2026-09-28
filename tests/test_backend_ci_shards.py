"""CI shard inventory must run every Backend test module exactly once."""

from pathlib import Path
import tempfile
import unittest

from scripts.ci.run_backend_shards import partition_test_files


class BackendShardTests(unittest.TestCase):
    def test_all_backend_modules_are_assigned_once(self):
        tests_dir = Path(__file__).resolve().parents[1] / "services/backend/tests"
        groups = partition_test_files(tests_dir)
        expected = set(tests_dir.glob("test_*.py"))
        actual = [path for group in groups for path in group]
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(set(actual), expected)
        self.assertTrue(all(groups))

    def test_rejects_inventory_smaller_than_shard_count(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "test_one.py").write_text("def test_one(): pass\n")
            with self.assertRaises(ValueError):
                partition_test_files(Path(directory))


if __name__ == "__main__":
    unittest.main()
