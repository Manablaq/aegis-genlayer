from __future__ import annotations

import http.client
import json
import threading
import unittest

from backend.api import make_server
from backend.engine import AegisEngine, StaticVerifier
from backend.models import Policy


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = AegisEngine(verifier=StaticVerifier())
        self.server = make_server(engine, port=0, api_token="test-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = str(self.server.server_address[0])
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: dict | None = None, token: str | None = "test-token"):
        connection = http.client.HTTPConnection(self.host, self.port)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        connection.request(method, path, body=json.dumps(body or {}), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_health_is_public_but_mutation_requires_token(self):
        status, body = self.request("GET", "/health", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        status, body = self.request("POST", "/v1/policies", {}, token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "UNAUTHORIZED")
        status, body = self.request("GET", "/v1/intents/" + "a" * 64, token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "UNAUTHORIZED")

    def test_cors_preflight_is_explicit_and_origin_bound(self):
        connection = http.client.HTTPConnection(self.host, self.port)
        connection.request(
            "OPTIONS",
            "/v1/intents",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "http://127.0.0.1:5173")
        self.assertIn("Authorization", response.getheader("Access-Control-Allow-Headers", ""))
        connection.close()

        connection = http.client.HTTPConnection(self.host, self.port)
        connection.request("OPTIONS", "/v1/intents", headers={"Origin": "https://untrusted.example"})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 204)
        self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
        connection.close()

    def test_policy_registration_is_reachable(self):
        status, body = self.request(
            "POST",
            "/v1/policies",
            {
                "policy_id": "p",
                "version": 1,
                "approved_agents": ["agent"],
                "allowed_action_types": ["pay"],
                "allowed_recipients": ["vendor"],
                "approved_sources": {"source": "https://source.example/api/"},
                "max_value": 1,
                "required_sources": ["source"],
                "minimum_attestations": 1,
                "maximum_age_seconds": 10,
                "intent_ttl_seconds": 10,
                "repair_window_seconds": 10,
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["status"], "REGISTERED")

    def test_direct_consensus_evaluation_is_disabled(self):
        status, body = self.request(
            "POST",
            "/v1/intents/" + "a" * 64 + "/evaluate",
            {"consensus_decision": "AUTHORIZE"},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body["error"], "GENLAYER_FINALITY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
