# Capped-relay policy comparison

20 runs. Cells show **median [minimum, maximum]** across runs.

- Each statistic summarizes run-level measurements; Objects are not pooled across runs.
- Ranges are observed run minima and maxima, not confidence intervals.
- Undefined values remain null. Each metric reports its defined and undefined run counts.
- Goodput retains all expected clients for the full phase, including terminated clients.
- Latency and late-Object fraction describe received Objects only; absent delivery has no P99.
- Termination counts/fractions cover the entire run and are repeated across phase rows.
- Relay RSS, CPU, and UDP egress are shared relay measurements repeated across cohorts.
- UDP egress includes QUIC overhead and retransmissions; payload goodput does not.
- Grouping uses settings available in analyzer output; verify other workload, burst, binary, and patch settings match before interpreting comparisons.

## 16 clients; cap 80 Mbit/s; pre_stall; all

Cohort: 16 clients. Phase: 3 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.18 [22.96, 23.57] | 4.000 [3.983, 4.003] | 4.000 [3.983, 4.003] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.31 [22.86, 24.47] | 4.000 [3.994, 4.003] | 4.000 [3.994, 4.003] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 23.63 [22.85, 23.80] | 4.000 [3.983, 4.011] | 4.000 [3.983, 4.011] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.03 [22.96, 23.92] | 4.000 [3.992, 4.003] | 4.000 [3.992, 4.003] | 50.0 [50.0, 50.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.66 [23.44, 24.08] | 41.0 [35.3, 42.5] | 66.039 [65.868, 66.195] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.67 [23.47, 24.27] | 39.0 [36.9, 47.6] | 66.007 [65.778, 66.153] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 23.89 [21.05, 24.27] | 38.7 [35.8, 40.5] | 66.139 [65.902, 66.228] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.80 [23.64, 24.81] | 41.1 [32.4, 45.2] | 66.012 [65.986, 66.314] | 0.0 [0.0, 0.0] |

## 16 clients; cap 80 Mbit/s; pre_stall; comparison_healthy

Cohort: 8 clients. Phase: 3 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.28 [22.83, 23.55] | 4.000 [3.989, 4.005] | 4.000 [3.989, 4.005] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.06 [22.78, 24.52] | 4.000 [4.000, 4.005] | 4.000 [4.000, 4.005] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 23.27 [22.75, 23.98] | 4.000 [3.983, 4.005] | 4.000 [3.983, 4.005] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.09 [22.98, 24.43] | 4.000 [3.989, 4.011] | 4.000 [3.989, 4.011] | 0.0 [0.0, 0.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.66 [23.44, 24.08] | 41.0 [35.3, 42.5] | 66.039 [65.868, 66.195] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.67 [23.47, 24.27] | 39.0 [36.9, 47.6] | 66.007 [65.778, 66.153] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 23.89 [21.05, 24.27] | 38.7 [35.8, 40.5] | 66.139 [65.902, 66.228] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.80 [23.64, 24.81] | 41.1 [32.4, 45.2] | 66.012 [65.986, 66.314] | 0.0 [0.0, 0.0] |

## 16 clients; cap 80 Mbit/s; pre_stall; stalled

Cohort: 8 clients. Phase: 3 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 23.76 [23.10, 24.26] | 4.000 [3.983, 4.017] | 4.000 [3.983, 4.017] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 22.98 [22.90, 23.66] | 4.000 [3.994, 4.000] | 4.000 [3.994, 4.000] | 100.0 [100.0, 100.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 23.89 [21.05, 24.27] | 38.7 [35.8, 40.5] | 66.139 [65.902, 66.228] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.80 [23.64, 24.81] | 41.1 [32.4, 45.2] | 66.012 [65.986, 66.314] | 0.0 [0.0, 0.0] |

## 16 clients; cap 80 Mbit/s; stall; all

Cohort: 16 clients. Phase: 15 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.62 [23.20, 26.93] | 4.000 [3.999, 4.000] | 4.000 [3.999, 4.000] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.39 [23.10, 26.53] | 4.000 [3.999, 4.002] | 4.000 [3.999, 4.002] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 10.85 [9.81, 13.64] | 2.000 [1.998, 2.004] | 2.000 [1.998, 2.004] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 10.64 [9.48, 11.42] | 2.000 [2.000, 2.002] | 2.000 [2.000, 2.002] | 50.0 [50.0, 50.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 27.81 [25.97, 28.00] | 42.6 [40.5, 45.2] | 66.065 [66.052, 66.089] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 28.25 [24.69, 28.89] | 42.5 [40.8, 44.6] | 66.042 [66.032, 66.075] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 32.84 [29.52, 33.53] | 19.3 [18.9, 20.5] | 33.071 [33.052, 33.097] | 8.0 [6.0, 8.0] |
| 8 | 3000 | 5 | 25.08 [22.17, 26.61] | 19.4 [17.9, 21.1] | 33.094 [33.074, 33.107] | 8.0 [7.0, 8.0] |

## 16 clients; cap 80 Mbit/s; stall; comparison_healthy

Cohort: 8 clients. Phase: 15 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.64 [23.19, 27.12] | 4.000 [3.999, 4.001] | 4.000 [3.999, 4.001] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.38 [23.06, 27.09] | 4.000 [3.998, 4.002] | 4.000 [3.998, 4.002] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 10.85 [9.81, 13.64] | 4.001 [3.997, 4.007] | 4.001 [3.997, 4.007] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 10.64 [9.48, 11.42] | 4.001 [3.999, 4.002] | 4.001 [3.999, 4.002] | 0.0 [0.0, 0.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 27.81 [25.97, 28.00] | 42.6 [40.5, 45.2] | 66.065 [66.052, 66.089] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 28.25 [24.69, 28.89] | 42.5 [40.8, 44.6] | 66.042 [66.032, 66.075] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 32.84 [29.52, 33.53] | 19.3 [18.9, 20.5] | 33.071 [33.052, 33.097] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 25.08 [22.17, 26.61] | 19.4 [17.9, 21.1] | 33.094 [33.074, 33.107] | 0.0 [0.0, 0.0] |

## 16 clients; cap 80 Mbit/s; stall; stalled

Cohort: 8 clients. Phase: 15 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 5.39 [5.39, 5.39] (1/5 defined) | 0.000 [0.000, 0.002] | 0.000 [0.000, 0.002] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 15.99 [12.38, 19.61] (2/5 defined) | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 100.0 [100.0, 100.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 32.84 [29.52, 33.53] | 19.3 [18.9, 20.5] | 33.071 [33.052, 33.097] | 8.0 [6.0, 8.0] |
| 8 | 3000 | 5 | 25.08 [22.17, 26.61] | 19.4 [17.9, 21.1] | 33.094 [33.074, 33.107] | 8.0 [7.0, 8.0] |

## 16 clients; cap 80 Mbit/s; recovery; all

Cohort: 16 clients. Phase: 10 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.25 [23.12, 69.01] | 4.001 [3.987, 4.002] | 4.001 [3.982, 4.002] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.33 [23.08, 25.48] | 4.002 [4.000, 4.003] | 4.002 [4.000, 4.003] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 14920.85 [14881.58, 14931.84] | 4.882 [4.849, 4.907] | 1.930 [1.902, 1.951] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 10.93 [9.52, 16.06] | 2.000 [2.000, 2.002] | 2.000 [2.000, 2.002] | 50.0 [50.0, 50.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 28.83 [26.00, 29.00] | 43.8 [42.5, 46.1] | 66.086 [65.850, 66.142] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 26.17 [25.72, 29.95] | 43.7 [38.6, 47.4] | 66.090 [66.033, 66.148] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 36.92 [34.55, 41.23] | 58.4 [56.7, 64.4] | 79.851 [79.769, 80.001] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.70 [21.89, 26.80] | 19.1 [18.8, 19.8] | 33.092 [33.015, 33.157] | 8.0 [8.0, 8.0] |

## 16 clients; cap 80 Mbit/s; recovery; comparison_healthy

Cohort: 8 clients. Phase: 10 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 23.37 [23.13, 75.78] | 4.002 [3.987, 4.003] | 4.002 [3.985, 4.003] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 23.28 [23.14, 25.48] | 4.003 [4.000, 4.007] | 4.003 [4.000, 4.007] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 189.62 [175.42, 206.17] | 3.988 [3.978, 4.000] | 3.860 [3.803, 3.902] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 10.93 [9.52, 16.06] | 4.000 [4.000, 4.003] | 4.000 [4.000, 4.003] | 0.0 [0.0, 0.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | off | 5 | 28.83 [26.00, 29.00] | 43.8 [42.5, 46.1] | 66.086 [65.850, 66.142] | 0.0 [0.0, 0.0] |
| 0 | 3000 | 5 | 26.17 [25.72, 29.95] | 43.7 [38.6, 47.4] | 66.090 [66.033, 66.148] | 0.0 [0.0, 0.0] |
| 8 | off | 5 | 36.92 [34.55, 41.23] | 58.4 [56.7, 64.4] | 79.851 [79.769, 80.001] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.70 [21.89, 26.80] | 19.1 [18.8, 19.8] | 33.092 [33.015, 33.157] | 0.0 [0.0, 0.0] |

## 16 clients; cap 80 Mbit/s; recovery; stalled

Cohort: 8 clients. Phase: 10 s. Timely-delivery target: 150 ms.

| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 14944.41 [14920.22, 14956.84] | 5.776 [5.720, 5.815] | 0.000 [0.000, 0.000] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | undefined (0/5) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 100.0 [100.0, 100.0] |

| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | off | 5 | 36.92 [34.55, 41.23] | 58.4 [56.7, 64.4] | 79.851 [79.769, 80.001] | 0.0 [0.0, 0.0] |
| 8 | 3000 | 5 | 23.70 [21.89, 26.80] | 19.1 [18.8, 19.8] | 33.092 [33.015, 33.157] | 8.0 [8.0, 8.0] |
