#!/usr/bin/env python3
"""Generate a short-lived certificate for a private experiment endpoint."""
import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import tempfile


def make_cert(out: Path, host: str) -> None:
    try:
        ipaddress.ip_address(host)
        san = f"IP:{host}"
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            raise ValueError("host must be an IP address or DNS hostname")
        san = f"DNS:{host}"
    out.mkdir(parents=True, exist_ok=True)
    if (out / "key.pem").exists() or (out / "cert.pem").exists():
        raise FileExistsError(f"refusing to replace an existing certificate in {out}")
    config = ("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n"
              f"[dn]\nCN={host}\n[ext]\nsubjectAltName={san}\n"
              "basicConstraints=critical,CA:TRUE\n"
              "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
              "extendedKeyUsage=serverAuth\n")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf") as f:
        f.write(config)
        f.flush()
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-nodes", "-days", "7", "-config", f.name,
                        "-keyout", str(out / "key.pem"),
                        "-out", str(out / "cert.pem")], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    (out / "key.pem").chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    make_cert(args.out, args.host)
