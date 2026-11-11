import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ice_worker import binary_configuration, experiment_options
from analyze_ice_isolation import merge_generators, summarize_distributed


def client_records(client, latency=-100):
    common = {"client": client, "role": "subscriber", "cohort": "healthy", "connection_id": 100 + client,
              "subscription_id": 0}
    return [{**common, "type": "ready", "timestamp_unix_us": 1_000_000},
            {**common, "type": "complete", "timestamp_unix_us": 11_000_000},
            {"type": "object", "client": client, "seq": 0, "bytes": 1000,
             "received_unix_us": 5_000_000, "latency_ms": latency}]


class IceIsolationTests(unittest.TestCase):
    def test_defaults_preserve_stock_policy_and_single_track(self):
        options, flags = experiment_options({}, 4)
        self.assertEqual(flags, [])
        self.assertEqual(options["tracks"], 1)
        self.assertFalse(options["allow_policy_termination"])

    def test_policy_and_multitrack_flags_are_validated(self):
        env = {"MOQT_APPLICATION_MBPS": "12", "MOQT_SCHEDULER": "drr",
               "MOQT_SESSION_BUFFER_BYTES": "2097152", "MOQT_MAX_GROUP_BYTES": "524288",
               "MOQT_TRACKS": "4", "MOQT_EXTRA_TRACK_CLIENTS": "1",
               "MOQT_TRACK_PRIORITIES": "0,128,128,128", "MOQT_ALLOW_POLICY_TERMINATION": "1"}
        options, flags = experiment_options(env, 4)
        self.assertEqual(flags[flags.index("--scheduler") + 1], "drr")
        self.assertEqual(options["track_priorities"], [0, 128, 128, 128])
        for bad in [{"MOQT_APPLICATION_MBPS": "nan"}, {"MOQT_SCHEDULER": "drr"},
                    {"MOQT_SESSION_BUFFER_BYTES": "10"}, {"MOQT_TRACKS": "0"},
                    {"MOQT_TRACKS": "2", "MOQT_TRACK_BITRATES": "4000000"},
                    {"MOQT_ALLOW_POLICY_TERMINATION": "yes"}]:
            with self.assertRaises(ValueError):
                experiment_options(bad, 4)

    def test_binary_manifest_rejects_either_mismatched_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relay, load, manifest = root / "relay", root / "load", root / "build.json"
            relay.write_bytes(b"relay")
            load.write_bytes(b"load")
            relay.chmod(0o700)
            load.chmod(0o700)
            data = {"binary_sha256": hashlib.sha256(b"relay").hexdigest(),
                    "client_binary_sha256": hashlib.sha256(b"load").hexdigest()}
            manifest.write_text(json.dumps(data))
            env = {"MOQT_RELAY_BINARY": str(relay), "MOQT_LOAD_BINARY": str(load), "MOQT_BUILD_MANIFEST": str(manifest)}
            self.assertEqual(binary_configuration(root, env)["binary_sha256"]["relay"], data["binary_sha256"])
            load.write_bytes(b"changed load")
            with self.assertRaisesRegex(ValueError, "load binary"):
                binary_configuration(root, env)
            load.write_bytes(b"load")
            relay.write_bytes(b"changed relay")
            with self.assertRaisesRegex(ValueError, "relay binary"):
                binary_configuration(root, env)

    def test_generator_merge_uses_global_client_ids(self):
        records = merge_generators([client_records(0), client_records(1)], 2)
        self.assertEqual(len(records), 6)
        for groups in [[client_records(0), client_records(0)], [client_records(0), client_records(2)]]:
            with self.assertRaises(ValueError):
                merge_generators(groups, 2)

    def test_unverified_clocks_allow_throughput_but_no_latency_claim(self):
        records = merge_generators([client_records(0), client_records(1)], 2)
        summary = summarize_distributed(records, 2, 10, 2, 1)
        self.assertEqual(summary["jain_session_throughput"], 1)
        self.assertGreater(summary["aggregate_throughput_mbps"], 0)
        self.assertIsNone(summary["clients"][0]["p99_latency_ms"])
        self.assertIsNone(summary["clients"][0]["timely_mbps"])
        self.assertEqual(records[2]["latency_ms"], -100, "raw records must not be altered")
        with self.assertRaisesRegex(ValueError, "invalid latency"):
            summarize_distributed(records, 2, 10, 2, 1, True)


if __name__ == "__main__":
    unittest.main()
