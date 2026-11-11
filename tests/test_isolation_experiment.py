import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from isolation_experiment import summarize_records, jain


def records():
    result = []
    for client, tracks in [(0, 2), (1, 1)]:
        sid = 40 + client
        ids = list(range(tracks))
        common = {"client": client, "role": "subscriber", "cohort": "healthy", "connection_id": sid,
                  "tracks": tracks, "subscription_ids": ids, "subscription_id": 0}
        result += [{**common, "type": "ready", "timestamp_unix_us": 1_000_000},
                   {**common, "type": "complete", "timestamp_unix_us": 11_000_000}]
        for track in range(tracks):
            result.append({**common, "type": "track_ready", "track": f"track-{track}", "subscription_id": track})
    return result


def obj(client, track, seq, size=1000):
    return {"type": "object", "client": client, "track": f"track-{track}", "seq": seq,
            "bytes": size, "received_unix_us": 5_000_000, "latency_ms": 100}


class IsolationSummaryTests(unittest.TestCase):
    def test_tracks_are_summed_within_one_session(self):
        data = records() + [obj(0, 0, 0), obj(0, 1, 0), obj(1, 0, 0, 2000)]
        summary = summarize_records(data, 2, 10, 2, 2)
        self.assertEqual([c["payload_bytes"] for c in summary["clients"]], [2000, 2000])
        self.assertEqual(summary["jain_session_throughput"], 1)
        self.assertEqual(summary["clients"][0]["tracks"], 2)

    def test_terminated_zero_delivery_client_stays_in_denominator(self):
        data = records() + [obj(0, 0, 0), {"type": "subscription_terminated", "client": 1,
                                          "track": "track-0", "status_code": 6}]
        summary = summarize_records(data, 2, 10, 2, 2)
        self.assertEqual(summary["jain_session_throughput"], .5)
        self.assertEqual(summary["clients"][1]["throughput_mbps"], 0)
        self.assertEqual(summary["clients"][1]["terminated_subscriptions"], 1)
        self.assertEqual(summary["window_seconds"], 8)

    def test_same_sequence_is_valid_across_tracks_but_duplicate_is_rejected(self):
        data = records() + [obj(0, 0, 1), obj(0, 1, 1)]
        summarize_records(data, 2, 10, 2, 2)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize_records(data + [obj(0, 0, 1)], 2, 10, 2, 2)

    def test_tracks_cannot_be_split_across_connections(self):
        data = records()
        next(e for e in data if e["type"] == "track_ready")["connection_id"] = 999
        with self.assertRaisesRegex(ValueError, "multiple QUIC"):
            summarize_records(data, 2, 10, 2, 2)

    def test_failed_client_and_timing_gap_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "client error"):
            summarize_records(records() + [{"type": "client_error", "client": 0}], 2, 10, 2, 2)
        data = records()
        next(e for e in data if e["type"] == "complete")["timestamp_unix_us"] += 2_000_000
        with self.assertRaisesRegex(ValueError, "wall-clock"):
            summarize_records(data, 2, 10, 2, 2)

    def test_invalid_latencies_and_changed_subscriptions_are_rejected(self):
        event = obj(0, 0, 0)
        event["latency_ms"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid latency"):
            summarize_records(records() + [event], 2, 10, 2, 2)
        data = records()
        next(e for e in data if e["type"] == "complete")["subscription_ids"] = [8, 9]
        with self.assertRaisesRegex(ValueError, "identities"):
            summarize_records(data, 2, 10, 2, 2)

    def test_all_zero_delivery_has_no_defined_fairness(self):
        self.assertIsNone(jain([0, 0]))
        self.assertIsNone(summarize_records(records(), 2, 10, 2, 2)["jain_session_throughput"])


if __name__ == "__main__":
    unittest.main()
