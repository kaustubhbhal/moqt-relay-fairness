import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("analysis", Path(__file__).resolve().parents[1] / "scripts/analyze.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class AnalysisTests(unittest.TestCase):
    def event(self, client, seq, seconds, latency=10):
        return {"type": "object", "client": client, "seq": seq,
                "received_unix_us": int(seconds * 1e6), "bytes": 125000,
                "latency_ms": latency}

    def test_missing_client_counts_as_zero(self):
        row = analysis.summarize_phase([self.event(0, 0, .5)], {0: 0, 1: 0}, [0, 1], 0, 1)
        self.assertEqual(row["zero_delivery_clients"], 1)
        self.assertEqual(row["mean_client_goodput_mbps"], .5)
        self.assertEqual(row["jain_goodput"], .5)

    def test_phase_boundaries_use_each_clients_ready_time(self):
        records = [self.event(0, 0, 1), self.event(0, 1, 2), self.event(1, 0, 2)]
        row = analysis.summarize_phase(records, {0: 0, 1: 1_000_000}, [0, 1], 1, 2)
        self.assertEqual(row["objects"], 2)
        self.assertEqual(row["mean_client_goodput_mbps"], 1)

    def test_late_delivery_separate_from_timely_goodput(self):
        row = analysis.summarize_phase([self.event(0, 0, .5, 500)], {0: 0}, [0], 0, 1)
        self.assertEqual(row["mean_client_goodput_mbps"], 1)
        self.assertEqual(row["mean_client_timely_goodput_mbps"], 0)
        self.assertEqual(row["late_object_fraction"], 1)

    def test_empty_latency_is_undefined_not_zero(self):
        row = analysis.summarize_phase([], {0: 0}, [0], 0, 1)
        self.assertIsNone(row["latency_p99_ms"])
        self.assertIsNone(row["jain_goodput"])
        self.assertEqual(row["zero_delivery_clients"], 1)

    def test_quantile_and_fairness(self):
        self.assertEqual(analysis.percentile(list(range(1, 101)), .99), 99)
        self.assertEqual(analysis.jain([4, 4, 4]), 1)

    def test_duplicate_and_negative_time_rejected(self):
        event = self.event(0, 0, .5)
        with self.assertRaises(ValueError):
            analysis.summarize_phase([event, event], {0: 0}, [0], 0, 1)
        event["latency_ms"] = -1
        with self.assertRaises(ValueError):
            analysis.summarize_phase([event], {0: 0}, [0], 0, 1)


if __name__ == "__main__":
    unittest.main()
