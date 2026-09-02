"""Focused tests for the isolated Bailian Higress route preparation."""

import unittest

from testweaver.runtime.higress_bailian_route import (
    Failure,
    build_provider_payload,
    build_route_payload,
    classify_bailian_endpoint,
    parse_protected_env_text,
    provider_readback,
    route_readback,
)


class HigressBailianRouteTests(unittest.TestCase):
    def test_bailian_compatible_endpoint_uses_qwen_provider_shape(self):
        self.assertEqual(
            classify_bailian_endpoint(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            "qwen",
        )

    def test_non_bailian_compatible_endpoint_uses_openai_shape(self):
        self.assertEqual(classify_bailian_endpoint("https://example.invalid/v1"), "openai")

    def test_provider_payload_keeps_secret_only_in_tokens_field(self):
        payload = build_provider_payload(
            name="testweaver-bailian",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="fixture-value",
            model="qwen-test",
        )

        self.assertEqual(payload["name"], "testweaver-bailian")
        self.assertEqual(payload["type"], "qwen")
        self.assertEqual(payload["protocol"], "openai/v1")
        self.assertEqual(payload["tokens"], ["fixture-value"])
        self.assertTrue(payload["rawConfigs"]["agentteamsMode"])

    def test_independent_route_is_exact_model_and_controller_scoped_auth(self):
        payload = build_route_payload(
            route_name="testweaver-bailian-route",
            domain="aigw-local.agentteams.io",
            provider_name="testweaver-bailian",
            source_model="deepseek-v4-flash",
            target_model="qwen-test",
        )

        self.assertEqual(
            payload["pathPredicate"],
            {"matchType": "PRE", "matchValue": "/testweaver-bailian/v1", "caseSensitive": False},
        )
        self.assertEqual(
            payload["upstreams"],
            [
                {
                    "provider": "testweaver-bailian",
                    "weight": 100,
                    "modelMapping": {"deepseek-v4-flash": "qwen-test"},
                }
            ],
        )
        self.assertEqual(
            payload["modelPredicates"],
            [{"matchType": "EXACT", "matchValue": "deepseek-v4-flash", "caseSensitive": False}],
        )
        self.assertEqual(
            payload["authConfig"],
            {"enabled": True, "allowedCredentialTypes": ["key-auth"]},
        )

    def test_protected_env_parser_returns_names_and_values_in_memory(self):
        parsed = parse_protected_env_text(
            "export AGENTTEAMS_BAILIAN_MODEL='qwen-test'\n"
            "AGENTTEAMS_BAILIAN_API_KEY=fixture-value\n"
            "# ignored\n"
        )

        self.assertEqual(
            parsed,
            {
                "AGENTTEAMS_BAILIAN_MODEL": "qwen-test",
                "AGENTTEAMS_BAILIAN_API_KEY": "fixture-value",
            },
        )

    def test_readback_verifies_shape_without_exposing_tokens(self):
        provider_meta = provider_readback(
            {
                "data": {
                    "name": "testweaver-bailian",
                    "type": "qwen",
                    "protocol": "openai/v1",
                    "tokens": ["fixture-value"],
                    "rawConfigs": {"agentteamsMode": True},
                }
            },
            "testweaver-bailian",
            "qwen",
        )
        self.assertEqual(provider_meta["token_count"], 1)
        self.assertNotIn("fixture-value", provider_meta)

        route = build_route_payload("testweaver-bailian-route", "aigw-local.agentteams.io", "testweaver-bailian", "deepseek-v4-flash", "qwen-test")
        route_meta = route_readback(
            {"data": route},
            {"name": "testweaver-bailian-route", "path": "/testweaver-bailian/v1", "provider": "testweaver-bailian", "source_model": "deepseek-v4-flash", "target_model": "qwen-test"},
        )
        self.assertEqual(route_meta["auth_scope"], "controller_managed")

    def test_permanent_readback_mismatch_fails_closed(self):
        route = build_route_payload("route", "domain", "provider", "deepseek-v4-flash", "qwen-test")
        with self.assertRaises(Failure):
            route_readback({"data": route}, {"name": "route", "path": "/wrong", "provider": "provider", "source_model": "deepseek-v4-flash", "target_model": "qwen-test"})

    def test_module_has_no_default_route_mutation_surface(self):
        source = __import__(
            "testweaver.runtime.higress_bailian_route",
            fromlist=["__file__"],
        ).__file__
        with open(source, encoding="utf-8") as module_file:
            source_text = module_file.read()
        self.assertNotIn("default-ai-route", source_text)
        self.assertNotIn("red_before_create", source_text)
        self.assertNotIn("bailian_after_create", source_text)
        self.assertIn("deepseek_unchanged", source_text)


if __name__ == "__main__":
    unittest.main()
