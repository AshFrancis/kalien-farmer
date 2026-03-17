"""Tests for kalien package — queue, state, settings, config, db, claimant validation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kalien.queue import QueueEntry, parse_queue_entry, push_queue_front, pop_queue, read_queue
from kalien.config import RunnerPaths
from kalien.state import save_state, load_state, clear_state
from kalien.settings import load_settings, save_settings, is_valid_claimant
from kalien.db import Database


class TestQueueParsing(unittest.TestCase):
    def test_full_entry(self):
        entry = parse_queue_entry("ABCD1234:12345:30:0:65536")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.seed, "ABCD1234")
        self.assertEqual(entry.seed_id, 12345)
        self.assertEqual(entry.salts, 30)
        self.assertEqual(entry.salt_start, 0)
        self.assertEqual(entry.beam, 65536)

    def test_minimal_entry(self):
        entry = parse_queue_entry("ABCD1234:12345")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.seed, "ABCD1234")
        self.assertEqual(entry.seed_id, 12345)
        self.assertIsNone(entry.salts)
        self.assertIsNone(entry.beam)

    def test_invalid_hex(self):
        self.assertIsNone(parse_queue_entry("NOTAHEX!:123"))

    def test_missing_seed_id(self):
        self.assertIsNone(parse_queue_entry("ABCD1234"))

    def test_bad_numbers(self):
        self.assertIsNone(parse_queue_entry("ABCD1234:notanumber"))

    def test_empty_string(self):
        self.assertIsNone(parse_queue_entry(""))


class TestQueueOperations(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue_path = Path(self.tmpdir) / "seed_queue.txt"

    def test_push_and_pop(self):
        push_queue_front(self.queue_path, "AAAA1111:100")
        push_queue_front(self.queue_path, "BBBB2222:200")
        line = pop_queue(self.queue_path, 32768)
        self.assertTrue(line.startswith("BBBB2222"))

    def test_pop_empty(self):
        self.assertIsNone(pop_queue(self.queue_path, 32768))

    def test_priority_pop(self):
        """Wide-beam entries should be popped first."""
        self.queue_path.write_text("AAA11111:100\nBBB22222:200:30:0:65536\n")
        line = pop_queue(self.queue_path, 32768)
        self.assertTrue(line.startswith("BBB22222"))

    def test_read_queue(self):
        self.queue_path.write_text("AAA11111:100\nBBB22222:200\n")
        lines = read_queue(self.queue_path)
        self.assertEqual(len(lines), 2)

    def test_read_empty(self):
        self.assertEqual(read_queue(self.queue_path), [])


class TestStateManagement(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "state.json"

    def test_save_load_clear(self):
        state = {"phase": "qualify", "seed": "ABCD1234", "best_score": 1000000}
        save_state(self.state_path, state)
        loaded = load_state(self.state_path)
        self.assertEqual(loaded["seed"], "ABCD1234")
        self.assertEqual(loaded["best_score"], 1000000)
        clear_state(self.state_path)
        self.assertIsNone(load_state(self.state_path))

    def test_load_missing(self):
        self.assertIsNone(load_state(self.state_path))


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = Path(self.tmpdir) / "settings.json"

    def test_defaults_no_file(self):
        settings = load_settings(self.settings_path)
        self.assertEqual(settings["claimant"], "")
        self.assertEqual(settings["push_threshold"], 1190000)

    def test_custom_settings(self):
        self.settings_path.write_text(json.dumps({
            "claimant": "GABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJKLMNOPQRSTUV",
            "push_threshold": 1200000,
        }))
        settings = load_settings(self.settings_path)
        self.assertTrue(settings["claimant"].startswith("G"))
        self.assertEqual(settings["push_threshold"], 1200000)

    def test_placeholder_claimant(self):
        self.settings_path.write_text(json.dumps({"claimant": "YOUR_STELLAR_ADDRESS_HERE"}))
        settings = load_settings(self.settings_path)
        self.assertEqual(settings["claimant"], "YOUR_STELLAR_ADDRESS_HERE")

    def test_save_and_reload(self):
        save_settings(self.settings_path, {"push_threshold": 1300000})
        settings = load_settings(self.settings_path)
        self.assertEqual(settings["push_threshold"], 1300000)


class TestClaimantValidation(unittest.TestCase):
    def test_valid_g_address(self):
        addr = "G" + "A" * 55
        self.assertTrue(is_valid_claimant(addr))

    def test_valid_c_address(self):
        addr = "C" + "B" * 55
        self.assertTrue(is_valid_claimant(addr))

    def test_empty(self):
        self.assertFalse(is_valid_claimant(""))

    def test_placeholder(self):
        self.assertFalse(is_valid_claimant("YOUR_STELLAR_ADDRESS_HERE"))

    def test_wrong_length(self):
        self.assertFalse(is_valid_claimant("GABC"))

    def test_wrong_prefix(self):
        addr = "X" + "A" * 55
        self.assertFalse(is_valid_claimant(addr))


class TestRunnerPaths(unittest.TestCase):
    def test_from_base(self):
        paths = RunnerPaths.from_base(Path("/tmp/test"))
        self.assertEqual(paths.state, Path("/tmp/test/state.json"))
        self.assertEqual(paths.queue, Path("/tmp/test/seed_queue.txt"))
        self.assertEqual(paths.pause, Path("/tmp/test/pause"))
        self.assertEqual(paths.db, Path("/tmp/test/kalien.db"))


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(Path(self.tmpdir) / "test.db")
        self.db.init_schema()

    def test_record_and_read(self):
        self.db.record_seed("ABCD1234", 100)
        seeds = self.db.read_seeds()
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["seed_hex"], "ABCD1234")
        self.assertEqual(seeds[0]["seed_id"], 100)

    def test_update_qualify(self):
        self.db.record_seed("ABCD1234", 100)
        self.db.update_qualify("ABCD1234", 1100000, "0x00000001", 300)
        seeds = self.db.read_seeds()
        self.assertEqual(seeds[0]["qualify_score"], 1100000)

    def test_update_push(self):
        self.db.record_seed("ABCD1234", 100)
        self.db.update_push("ABCD1234", "running", beam=65536, salts_total=30)
        seeds = self.db.read_seeds()
        self.assertEqual(seeds[0]["push_status"], "running")
        self.assertEqual(seeds[0]["push_beam"], 65536)

    def test_update_submitted(self):
        self.db.record_seed("ABCD1234", 100)
        self.db.update_submitted("ABCD1234", 1200000, "job-123")
        seeds = self.db.read_seeds()
        self.assertEqual(seeds[0]["submitted_score"], 1200000)
        self.assertEqual(seeds[0]["submitted_job_id"], "job-123")

    def test_duplicate_seed_ignored(self):
        self.db.record_seed("ABCD1234", 100)
        self.db.record_seed("ABCD1234", 100)  # should not raise
        seeds = self.db.read_seeds()
        self.assertEqual(len(seeds), 1)


if __name__ == "__main__":
    unittest.main()
