import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).resolve().parents[1] / "scripts/analyze_recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def objects(self, start=0, count=30, fps=30, latency=10):
        return [{"type": "object", "client": 0, "seq": i, "bytes": 1000,
                 "received_unix_us": round((start + i / fps) * 1e6), "latency_ms": latency}
                for i in range(count)]

    def measure(self, objects, **kwargs):
        return recovery.client_measurements(objects, 0, 10_000_000, 30, 150, **kwargs)

    def test_first_timely_is_not_sustained_recovery(self):
        row = self.measure(self.objects(count=1))
        self.assertEqual(row["first_timely_seconds"], 0)
        self.assertIsNone(row["sustained_timely_seconds"])

    def test_full_window_recovers_from_first_event(self):
        row = self.measure(self.objects(start=.25))
        self.assertEqual(row["first_timely_seconds"], .25)
        self.assertEqual(row["sustained_timely_seconds"], .25)

    def test_late_object_breaks_otherwise_dense_window(self):
        objects = self.objects()
        objects[15]["latency_ms"] = 500
        self.assertIsNone(self.measure(objects)["sustained_timely_seconds"])

    def test_burst_or_long_gap_does_not_count_as_recovery(self):
        self.assertIsNone(self.measure(self.objects(count=30, fps=300))["sustained_timely_seconds"])
        objects = self.objects(count=33)
        objects = [o for o in objects if not 400_000 <= o["received_unix_us"] <= 600_000]
        self.assertIsNone(self.measure(objects)["sustained_timely_seconds"])

    def test_80_percent_and_full_observation_required(self):
        self.assertIsNotNone(self.measure(self.objects(count=24, fps=24))["sustained_timely_seconds"])
        self.assertIsNone(self.measure(self.objects(count=23, fps=23))["sustained_timely_seconds"])
        self.assertIsNone(self.measure(self.objects(start=9.5))["sustained_timely_seconds"])

    def test_termination_preserves_null_times_and_fixed_rates(self):
        row = self.measure([], terminated=True)
        self.assertIsNone(row["first_timely_seconds"])
        self.assertIsNone(row["sustained_timely_seconds"])
        self.assertEqual(row["first5_payload_mbps"], 0)
        row = self.measure(self.objects(count=1), terminated=True)
        self.assertEqual(row["first5_payload_mbps"], .0016)
        self.assertIsNone(row["first_timely_seconds"])

    def test_censored_late_traffic_is_not_erased(self):
        row = self.measure(self.objects(count=30, latency=1000))
        self.assertIsNone(row["first_timely_seconds"])
        self.assertEqual(row["first5_payload_mbps"], .048)
        self.assertEqual(row["first5_timely_mbps"], 0)

    def test_fixed_windows_and_received_sequence_gaps(self):
        objects = self.objects(count=4)
        for event, seq, seconds in zip(objects, [5, 8, 7, 9], [0, 4.9, 5, 9.9]):
            event.update(seq=seq, received_unix_us=round(seconds * 1e6))
        row = self.measure(objects)
        self.assertEqual(row["received_sequence_gaps"], 1)
        self.assertEqual(row["first5_payload_mbps"], .0032)
        self.assertEqual(row["final5_payload_mbps"], .0032)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.measure(objects + [objects[0]])
        with self.assertRaisesRegex(ValueError, "five"):
            recovery.client_measurements([], 0, 4_000_000, 30, 150)

    def test_group_counts_show_censored_and_terminated_clients(self):
        clients = []
        for index, (data, terminal) in enumerate(((self.objects(), False), ([], False), ([], True))):
            clients.append(dict(self.measure(data, terminated=terminal), client=index, cohort="stalled",
                                terminated=terminal, subgroup_resets_total=0))
        group = recovery.group_runs([{"run": "r1", "settings": {"stall_for": 15}, "clients": clients}])[0]
        self.assertEqual(group["client_observations"], 3)
        self.assertEqual(group["sustained_timely_seconds_recovered_clients"], 1)
        self.assertEqual(group["terminated_clients"], 1)
        self.assertEqual(group["sustained_censored_clients"], 1)
        self.assertEqual(group["metrics"]["first5_payload_mbps"]["median"], .016)

    def test_run_validation_actual_resume_and_gzip(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            config = {"clients": 2, "stall_clients": 1, "duration": 12, "stall_after": 2,
                      "stall_for": 2, "fps": 30, "max_subgroup_age_ms": None}
            (path / "manifest.json").write_text(json.dumps({"status": "complete", "config": config}))
            events = []
            for client in range(2):
                events.extend([{"type": "ready", "client": client, "timestamp_unix_us": 0},
                               {"type": "complete", "client": client, "timestamp_unix_us": 12_001_000}])
            events.extend([{"type": "stall_begin", "client": 0, "timestamp_unix_us": 2_000_000},
                           {"type": "stall_end", "client": 0, "timestamp_unix_us": 4_100_000}])
            for phase in ("stall_begin", "stall_end"):
                events.append({"type": "quic_stats", "client": 0, "phase": phase,
                               **{key: 0 for key in ("udp_rx_bytes", "rx_stream_frames", "rx_data_blocked",
                                                    "rx_stream_data_blocked", "tx_acks", "tx_max_data")}})
            events.extend(self.objects(start=4.2))
            for name in ("process", "publisher", "metrics"):
                (path / f"{name}.jsonl").write_text("")
            def write_events():
                with gzip.open(path / "subscribers.jsonl.gz", "wt") as f:
                    f.write("\n".join(json.dumps(e) for e in events))
            write_events()
            run = recovery.summarize_run(path)
            self.assertEqual(run["clients"][0]["reference_unix_us"], 4_100_000)
            self.assertEqual(run["clients"][0]["first_timely_seconds"], .1)
            self.assertEqual(run["clients"][1]["reference_kind"], "nominal_control")
            config["allow_subgroup_reset"] = True
            (path / "manifest.json").write_text(json.dumps({"status": "complete", "config": config}))
            with self.assertRaisesRegex(ValueError, "connection"):
                recovery.summarize_run(path)
            for client in range(2):
                events.append({"type": "connection", "client": client, "timestamp_unix_us": 0})
                for event in events:
                    if event.get("client") == client and event["type"] in ("ready", "complete"):
                        event.update(connection_id=100 + client, subscription_id=0)
            events.append({"type": "subgroup_reset", "client": 0, "code": 2,
                           "group_id": 1, "subgroup_id": 0, "timestamp_unix_us": 4_110_000})
            write_events()
            run = recovery.summarize_run(path)
            self.assertTrue(run["clients"][0]["identity_checked"])
            self.assertEqual(run["clients"][0]["subgroup_resets_total"], 1)
            events[1]["connection_id"] = 999
            write_events()
            with self.assertRaisesRegex(ValueError, "changed connection_id"):
                recovery.summarize_run(path)
            events[1]["connection_id"] = 100
            events[1]["timestamp_unix_us"] = 120_000_000
            write_events()
            with self.assertRaisesRegex(ValueError, "suspension"):
                recovery.summarize_run(path)


if __name__ == "__main__":
    unittest.main()
