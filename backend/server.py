from __future__ import annotations

import os

from .api import make_server
from .engine import AegisEngine, Ed25519Verifier
from .store import JsonStore


def main() -> None:
    key_json = os.environ.get("AEGIS_PROVIDER_KEYS", "{}")
    import json

    public_keys = json.loads(key_json)
    engine = AegisEngine(
        verifier=Ed25519Verifier(public_keys),
        store=JsonStore(os.environ.get("AEGIS_STATE_FILE", "aegis.state.json")),
    )
    server = make_server(engine, host=os.environ.get("AEGIS_HOST", "127.0.0.1"), port=int(os.environ.get("AEGIS_PORT", "8081")))
    print(f"Aegis backend listening on {server.server_address[0]}:{server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
