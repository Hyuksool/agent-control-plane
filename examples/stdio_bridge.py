from __future__ import annotations

import hashlib
import json
import sys


def main() -> int:
    request = json.load(sys.stdin)
    instruction_hash = hashlib.sha256(request["instruction"].encode("utf-8")).hexdigest()
    response = {
        "success": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "output": f"protocol-smoke:{request['kind']}:{instruction_hash[:12]}",
        "error_code": None,
    }
    json.dump(response, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
