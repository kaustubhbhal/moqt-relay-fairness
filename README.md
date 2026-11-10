# MoQT relay fairness

CS 4251 Group 16's experiment setup for studying how stalled subscribers affect a Media over QUIC relay.

The first milestone measures the existing relay. It does not yet implement the cross-session scheduler proposed in Progress Report 1. We use actual QUIC connections and synthetic, paced media objects; these are transport experiments, not video playback tests.

Cloudflare's relay is pinned to draft-16 revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443` under `vendor/moq-rs`. Keeping the version fixed makes repeated experiments comparable with our submitted report. Initialize it with `git submodule update --init --recursive` after cloning.

See [the experiment design](docs/experiment-design.md) for the question and measurement boundaries. Local run instructions, results, and the PACE ICE procedure are added alongside the working harness.
