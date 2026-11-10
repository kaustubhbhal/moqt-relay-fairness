#!/usr/bin/env python3
"""Copy a completed matrix's public measurement files, excluding TLS keys."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    schedule = json.loads((args.matrix / "schedule.json").read_text())
    # Validate every run before creating an archive that could look complete.
    for run in schedule["runs"]:
        manifest = json.loads((args.matrix / run["directory"] / "manifest.json").read_text())
        if manifest["status"] != "complete":
            raise ValueError(f"unfinished/failed run: {run['directory']}")
    args.out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.matrix / "schedule.json", args.out)
    for run in schedule["runs"]:
        source = args.matrix / run["directory"]
        dest = args.out / run["directory"]
        dest.mkdir()
        shutil.copy2(source / "manifest.json", dest)
        for name in ("publisher.jsonl", "subscribers.jsonl", "process.jsonl", "metrics.jsonl",
                     "relay.stderr", "publisher.stderr", "subscribers.stderr"):
            with (source / name).open("rb") as src, (dest / (name + ".gz")).open("wb") as out:
                with gzip.GzipFile(filename="", fileobj=out, mode="wb", mtime=0) as compressed:
                    shutil.copyfileobj(src, compressed)
    lines = []
    for file in sorted(args.out.rglob("*")):
        if file.is_file():
            lines.append(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.relative_to(args.out)}")
    (args.out / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
