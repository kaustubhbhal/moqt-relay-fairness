#!/usr/bin/env python3
"""Build an isolated, patch-identified relay without modifying vendor/moq-rs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "3b2b584b47e4a18f3a6bf48dc9a665c736743443"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--patch", type=Path, default=ROOT / "patches/0001-egress-cap-and-subgroup-timeout.patch")
    p.add_argument("--target-dir", type=Path, default=ROOT / ".local/variant-target")
    args = p.parse_args()
    patch = args.patch.resolve()
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()
    build = ROOT / ".local/relay-variants" / digest[:16]
    source = build / "source"
    build.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT / "vendor/moq-rs"), str(source)], check=True)
        subprocess.run(["git", "checkout", "--quiet", BASE], cwd=source, check=True)
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
        # Include added files in the reproducibility diff without committing upstream.
        subprocess.run(["git", "add", "-N", "."], cwd=source, check=True)
    actual = subprocess.check_output(["git", "diff", "--no-ext-diff", "--binary"], cwd=source)
    if actual != patch.read_bytes():
        raise RuntimeError(f"existing variant source differs from its patch; preserve and inspect {source}")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() != BASE:
        raise RuntimeError("variant base revision differs from the pinned relay")
    target = args.target_dir.resolve()
    command = ["cargo", "+1.90.0", "build", "--release", "--locked", "-p", "moq-relay-ietf", "--features", "metrics-prometheus"]
    subprocess.run(command, cwd=source, env={**os.environ, "CARGO_TARGET_DIR": str(target)}, check=True)
    binary = build / "moq-relay-ietf"
    shutil.copy2(target / "release/moq-relay-ietf", binary)
    manifest = {"base_revision": BASE, "patch_sha256": digest, "patch": str(patch),
                "binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "build_command": command,
                "rustc": subprocess.check_output(["rustc", "+1.90.0", "--version"], text=True).strip()}
    (build / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
