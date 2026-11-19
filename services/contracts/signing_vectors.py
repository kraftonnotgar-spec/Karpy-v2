"""Recompute and verify the shared HMAC signing test vectors.

Stdlib only. Run from anywhere:

    python services/contracts/signing_vectors.py

Exit code 0 means every vector in signing-vectors.json reproduces exactly
(body hash, canonical string and signature). Any language implementation of
the Karpy service contract should be checked against the same JSON file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

SCHEME = "KARPY-HMAC-SHA256-V1"
VECTORS = Path(__file__).with_name("signing-vectors.json")


def canonical_string(key_id: str, method: str, path_and_query: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join(
        (SCHEME, key_id, method.upper(), path_and_query, timestamp, nonce, hashlib.sha256(body).hexdigest())
    )


def signature_header(secret: str, canonical: str) -> str:
    return "v1=" + hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def main() -> int:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    if data["scheme"] != SCHEME:
        print(f"unexpected scheme {data['scheme']!r}")
        return 1
    failures = 0
    for v in data["vectors"]:
        body = v["body"].encode()
        canonical = canonical_string(v["key_id"], v["method"], v["path_and_query"], v["timestamp"], v["nonce"], body)
        header = signature_header(v["secret"], canonical)
        checks = {
            "body_sha256": hashlib.sha256(body).hexdigest() == v["body_sha256"],
            "canonical_string": canonical == v["canonical_string"],
            "signature_header": header == v["signature_header"],
        }
        ok = all(checks.values())
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {v['name']}: {header}" + ("" if ok else f" {checks}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
