from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime as DateTime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from testweaver.observability.readonly_query import Correlation, ProtectedConfigRef
from testweaver.observability.sls_query import (
    EVALUATION_DETAIL_LOGSTORE,
    SlsBinding,
    SlsCredentials,
    SlsHttpResponse,
    SlsReadOnlyQueryClient,
    _canonical_resource,
    _signed_headers,
    _query_text,
    load_sls_binding,
    protected_csv_credential_provider,
    protected_env_credential_provider,
)


_HASH = "sha256:" + "a" * 64


def _correlation() -> Correlation:
    return Correlation("campaign-ref", "run-ref", "pg-ref", _HASH)


def _ref(path: Path) -> ProtectedConfigRef:
    return ProtectedConfigRef(path=path, variable_names=("ALIBABA_CLOUD_ACCESS_KEY_ID",))


def _binding(*, agent_space: str | None = "space-ref", logstore: str = "trace-log") -> SlsBinding:
    return SlsBinding(
        endpoint="http://127.0.0.1:18081",
        project="project-ref",
        logstore=logstore,
        agent_space=agent_space,
    )


def _credentials() -> SlsCredentials:
    return SlsCredentials("access-id-fixture", "secret-fixture")


class SlsQueryContractTests(unittest.TestCase):
    def test_trace_getlogs_is_signed_and_verifies_one_exact_row(self) -> None:
        requests: list[tuple[str, dict[str, str]]] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del timeout
            requests.append((url, headers))
            return SlsHttpResponse(
                200,
                json.dumps(
                    [
                        {
                            "run_id": "run-ref",
                            "campaign_id": "campaign-ref",
                            "pg_revision": "pg-ref",
                            "content_hash": _HASH,
                            "agentSpace": "space-ref",
                            "trace_id": "b" * 32,
                        }
                    ]
                ).encode(),
                {"x-log-requestid": "request-id-fixture"},
            )

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            client = SlsReadOnlyQueryClient(
                binding=_binding(),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            )

            receipt = client.query_trace(
                correlation=_correlation(),
                start_time_s=100,
                end_time_s=200,
                trace_id="b" * 32,
            )

        self.assertEqual(receipt.status, "VERIFIED")
        self.assertTrue(receipt.read_only)
        self.assertFalse(receipt.live_claim)
        self.assertEqual(receipt.logstore, "trace-log")
        self.assertTrue(receipt.request_id_present)
        parsed = urlsplit(requests[0][0])
        self.assertEqual(parsed.path, "/logstores/trace-log")
        params = parse_qs(parsed.query)
        self.assertEqual(params["type"], ["log"])
        self.assertNotIn("FROM log", params["query"][0])
        self.assertEqual(params["query"], ["* | SELECT * LIMIT 100"])
        self.assertTrue(requests[0][1]["Authorization"].startswith("LOG access-id-fixture:"))
        serialized = json.dumps(receipt.as_dict(), sort_keys=True)
        self.assertNotIn("secret-fixture", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_evaluation_detail_uses_the_authoritative_logstore(self) -> None:
        requests: list[str] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del headers, timeout
            requests.append(url)
            return SlsHttpResponse(
                200,
                json.dumps(
                    [
                        {
                            "runId": "run-ref",
                            "campaignId": "campaign-ref",
                            "pgRevision": "pg-ref",
                            "contentHash": _HASH,
                            "agentSpace": "space-ref",
                        }
                    ]
                ).encode(),
            )

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            receipt = SlsReadOnlyQueryClient(
                binding=_binding(logstore="configured-trace"),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            ).query_evaluation_detail(
                correlation=_correlation(), start_time_s=100, end_time_s=200
            )

        self.assertEqual(receipt.status, "VERIFIED")
        self.assertEqual(receipt.logstore, EVALUATION_DETAIL_LOGSTORE)
        self.assertIn("/logstores/evaluation_detail?", requests[0])

    def test_sls_signature_uses_sorted_decoded_query_parameters(self) -> None:
        url = (
            "https://project-ref.cn-beijing.log.aliyuncs.com/logstores/trace-log?"
            "z=last&query=%2A%20%7C%20SELECT%20%27%25%27&space=a%20b"
        )
        fixed_date = DateTime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
        with patch("testweaver.observability.sls_query.datetime") as clock:
            clock.now.return_value = fixed_date
            headers = _signed_headers("GET", url, _credentials())

        resource = _canonical_resource(url)
        self.assertEqual(
            resource,
            "/logstores/trace-log?query=* | SELECT '%'&space=a b&z=last",
        )
        # Independent fixed vector from the SLS HMAC-SHA1 signing contract;
        # this assertion must not derive its expected value from the signer.
        self.assertEqual(
            headers["Authorization"],
            "LOG access-id-fixture:8v/YQ7/aKX8FTn09HWC3Z1qQ0wQ=",
        )

    def test_query_syntax_has_no_from_log_clause(self) -> None:
        query = _query_text(_correlation(), "space-ref", "b" * 32)
        self.assertEqual(query, "* | SELECT * LIMIT 100")
        self.assertNotIn("FROM log", query)

    def test_pilot_host_only_endpoint_is_normalized_but_wrong_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.json"
            path.write_text(
                json.dumps(
                    {
                        "sls": {
                            "endpoint": "project-ref.cn-beijing.log.aliyuncs.com",
                            "project": "project-ref",
                            "logstore": "trace-log",
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            binding = load_sls_binding(path, agent_space="space-ref")
            self.assertEqual(binding.safe_endpoint, "https://project-ref.cn-beijing.log.aliyuncs.com")
            self.assertEqual(binding.logstore, "trace-log")

            path.write_text(
                json.dumps(
                    {
                        "sls": {
                            "endpoint": "other-project.cn-beijing.log.aliyuncs.com",
                            "project": "project-ref",
                            "logstore": "trace-log",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "host does not match project"):
                load_sls_binding(path, agent_space="space-ref")

    def test_sls_binding_requires_configured_trace_logstore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.json"
            path.write_text(
                json.dumps(
                    {
                        "sls": {
                            "endpoint": "project-ref.cn-beijing.log.aliyuncs.com",
                            "project": "project-ref",
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            with self.assertRaisesRegex(ValueError, "logstore"):
                load_sls_binding(path, agent_space="space-ref")

    def test_protected_env_provider_reads_selected_credentials_without_repr_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.env"
            path.write_text(
                "ALIBABA_CLOUD_ACCESS_KEY_ID=id-fixture\n"
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET=secret-fixture\n"
                "UNUSED=not-read\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            credentials = protected_env_credential_provider(path)()

        self.assertEqual(credentials.access_key_id, "id-fixture")
        self.assertEqual(repr(credentials), "SlsCredentials(access_key_id_present=True, secret_present=True, token_present=False)")
        self.assertNotIn("secret-fixture", repr(credentials))

    def test_protected_csv_provider_requires_owner_only_single_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AccessKey.csv"
            path.write_text(
                "AccessKey ID,AccessKey Secret\n"
                "id-fixture,secret-fixture\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            credentials = protected_csv_credential_provider(path)()
            self.assertEqual(credentials.access_key_id, "id-fixture")

            os.chmod(path, 0o644)
            with self.assertRaisesRegex(ValueError, "owner-only"):
                protected_csv_credential_provider(path)()

    def test_regional_sls_endpoint_is_project_qualified_for_getlogs(self) -> None:
        requests: list[tuple[str, dict[str, str]]] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del timeout
            requests.append((url, headers))
            return SlsHttpResponse(
                200,
                json.dumps(
                    [
                        {
                            "run_id": "run-ref",
                            "campaign_id": "campaign-ref",
                            "pg_revision": "pg-ref",
                            "content_hash": _HASH,
                            "agentSpace": "space-ref",
                        }
                    ]
                ).encode(),
            )

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            receipt = SlsReadOnlyQueryClient(
                binding=SlsBinding(
                    endpoint="https://cn-hangzhou.log.aliyuncs.com",
                    project="project-ref",
                    logstore="trace-log",
                    agent_space="space-ref",
                ),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            ).query_trace(correlation=_correlation(), start_time_s=100, end_time_s=200)

        self.assertEqual(receipt.status, "VERIFIED")
        parsed = urlsplit(requests[0][0])
        self.assertEqual(parsed.netloc, "project-ref.cn-hangzhou.log.aliyuncs.com")
        self.assertTrue(requests[0][1]["Authorization"].startswith("LOG access-id-fixture:"))

    def test_cms_paths_and_non_sls_hosts_are_rejected(self) -> None:
        for endpoint in (
            "https://cn-hangzhou.log.aliyuncs.com/api/cms",
            "https://project-ref.example.com",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    SlsBinding(
                        endpoint=endpoint,
                        project="project-ref",
                        logstore="trace-log",
                        agent_space="space-ref",
                    )

    def test_official_https_endpoint_rejects_explicit_port_but_loopback_http_allows_it(self) -> None:
        with self.assertRaisesRegex(ValueError, "official HTTPS"):
            SlsBinding(
                endpoint="https://cn-hangzhou.log.aliyuncs.com:8443",
                project="project-ref",
                logstore="trace-log",
                agent_space="space-ref",
            )
        local = SlsBinding(
            endpoint="http://127.0.0.1:18081",
            project="project-ref",
            logstore="trace-log",
            agent_space="space-ref",
        )
        self.assertEqual(local.safe_endpoint, "http://127.0.0.1:18081")

    def test_missing_agent_space_is_not_a_row_requirement_but_missing_ram_blocks(self) -> None:
        calls: list[bool] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del url, headers, timeout
            calls.append(True)
            return SlsHttpResponse(200, b"[]")

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            no_space = SlsReadOnlyQueryClient(
                binding=_binding(agent_space=None),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            )
            no_credential = SlsReadOnlyQueryClient(
                binding=_binding(), transport=transport
            )

            self.assertEqual(no_space.preflight()["status"], "NOT_VERIFIED")
            self.assertEqual(no_credential.preflight()["reason"], "sls_ram_credential_reference_missing")
            no_space_receipt = no_space.query_trace(
                correlation=_correlation(), start_time_s=100, end_time_s=200
            )
            no_credential_receipt = no_credential.query_trace(
                correlation=_correlation(), start_time_s=100, end_time_s=200
            )

        self.assertEqual(no_space_receipt.status, "NOT_VERIFIED")
        self.assertEqual(no_credential_receipt.status, "BLOCKED")
        self.assertEqual(calls, [True])

    def test_gen_ai_lineage_aliases_verify_in_one_row_without_agent_space(self) -> None:
        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del url, headers, timeout
            return SlsHttpResponse(
                200,
                json.dumps(
                    [
                        {
                            "gen_ai.session.id": "run-ref",
                            "gen_ai.conversation.id": "campaign-ref",
                            "testweaver.pg.revision": "pg-ref",
                            "testweaver.content.hash": _HASH,
                            "traceId": "b" * 32,
                        }
                    ]
                ).encode(),
                {"x-log-requestid": "request-id-fixture"},
            )

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            receipt = SlsReadOnlyQueryClient(
                binding=_binding(agent_space="space-ref"),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            ).query_trace(
                correlation=_correlation(),
                start_time_s=100,
                end_time_s=200,
                trace_id="b" * 32,
            )

        self.assertEqual(receipt.status, "VERIFIED")
        self.assertEqual(receipt.matched_row_count, 1)

    def test_permission_failure_is_hash_only(self) -> None:
        body = b"permission denied with sensitive server detail"

        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del url, headers, timeout
            return SlsHttpResponse(403, body, {"x-log-requestid": "request-id-fixture"})

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            receipt = SlsReadOnlyQueryClient(
                binding=_binding(),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            ).query_trace(correlation=_correlation(), start_time_s=100, end_time_s=200)

        self.assertEqual(receipt.status, "BLOCKED")
        self.assertEqual(receipt.reason, "sls_query_non_success")
        self.assertEqual(receipt.response_hash, "sha256:" + hashlib.sha256(body).hexdigest())
        serialized = json.dumps(receipt.as_dict(), sort_keys=True)
        self.assertNotIn(body.decode(), serialized)
        self.assertNotIn("secret-fixture", serialized)

    def test_partial_rows_cannot_be_stitched_into_a_verified_readback(self) -> None:
        def transport(url: str, headers: dict[str, str], timeout: float) -> SlsHttpResponse:
            del url, headers, timeout
            return SlsHttpResponse(
                200,
                json.dumps(
                    [
                        {"run_id": "run-ref", "agentSpace": "space-ref"},
                        {"campaign_id": "campaign-ref", "pg_revision": "pg-ref", "content_hash": _HASH},
                    ]
                ).encode(),
            )

        with tempfile.TemporaryDirectory() as directory:
            ref_path = Path(directory) / "ram-ref"
            ref_path.write_text("REFERENCE_ONLY=1\n", encoding="utf-8")
            os.chmod(ref_path, 0o600)
            receipt = SlsReadOnlyQueryClient(
                binding=_binding(),
                credential_ref=_ref(ref_path),
                credential_provider=_credentials,
                transport=transport,
            ).query_trace(correlation=_correlation(), start_time_s=100, end_time_s=200)

        self.assertEqual(receipt.status, "NOT_VERIFIED")
        self.assertEqual(receipt.matched_row_count, 0)


if __name__ == "__main__":
    unittest.main()
