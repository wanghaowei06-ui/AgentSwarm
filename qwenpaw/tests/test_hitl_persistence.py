import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest


class _ApprovalChannel:
    def __init__(self) -> None:
        self.notifications: list[dict] = []

    async def send_approval_notification(self, **payload) -> None:
        self.notifications.append(payload)


class _FlakyChannelManager:
    def __init__(self, channel: _ApprovalChannel) -> None:
        self.channel = channel
        self.attempts = 0

    async def get_channel(self, _name: str):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("channel is still starting")
        return self.channel


class PersistentApprovalTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_working_dir = os.environ.get("QWENPAW_WORKING_DIR")
        self.old_timeout = os.environ.get(
            "AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS",
        )
        os.environ["QWENPAW_WORKING_DIR"] = self.tmpdir.name
        os.environ["AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS"] = "1"

    def tearDown(self) -> None:
        if self.old_working_dir is None:
            os.environ.pop("QWENPAW_WORKING_DIR", None)
        else:
            os.environ["QWENPAW_WORKING_DIR"] = self.old_working_dir
        if self.old_timeout is None:
            os.environ.pop("AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS", None)
        else:
            os.environ["AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS"] = self.old_timeout
        self.tmpdir.cleanup()

    @staticmethod
    def _summary():
        from qwenpaw.app.approvals.models import ApprovalRequestSummary

        return ApprovalRequestSummary(
            source_type="driver_policy",
            name="driver:mcp:testweaver",
            severity="medium",
            findings_count=1,
            result_summary="requires Human approval",
        )

    async def _new_service(self):
        from qwenpaw.app.approvals.service import ApprovalService
        from qwenpaw_worker.hitl import install_qwenpaw_approval_persistence

        install_qwenpaw_approval_persistence()
        return ApprovalService()

    async def test_pending_request_survives_service_restart(self) -> None:
        service = await self._new_service()
        pending = await service.create_pending_summary(
            session_id="session-1",
            root_session_id="session-1",
            owner_agent_id="default",
            user_id="@human:example",
            channel="",
            agent_id="default",
            summary=self._summary(),
            extra={
                "driver": {
                    "protocol": "mcp",
                    "operation": "call",
                    "api_key": "do-not-persist",
                },
                "_channel_instance": object(),
            },
        )

        restarted = await self._new_service()
        restored = await restarted.get_request(pending.request_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.request_id, pending.request_id)
        self.assertEqual(restored.status, "pending")
        self.assertNotIn("_channel_instance", restored.extra)

        state_path = Path(self.tmpdir.name) / "agentteams-hitl.json"
        state_text = state_path.read_text(encoding="utf-8")
        self.assertNotIn("do-not-persist", state_text)

        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        waiter = asyncio.create_task(
            restarted.wait_for_approval(
                pending.request_id,
                timeout_seconds=1,
            ),
        )
        await asyncio.sleep(0)
        resolved = await restarted.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(await waiter, ApprovalDecision.APPROVED)

        state_path = Path(self.tmpdir.name) / "agentteams-hitl.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["records"][pending.request_id]["status"],
            "approved",
        )

        self.assertIsNone(
            await restarted.resolve_request(
                pending.request_id,
                ApprovalDecision.DENIED,
            ),
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["records"][pending.request_id]["status"],
            "approved",
        )

    async def test_cancel_is_durable_and_does_not_change_on_duplicate_resolution(self) -> None:
        service = await self._new_service()
        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        pending = await service.create_pending_summary(
            session_id="session-cancel",
            root_session_id="session-cancel",
            owner_agent_id="default",
            user_id="@human:example",
            channel="",
            agent_id="default",
            summary=self._summary(),
        )

        self.assertEqual(
            await service.cancel_all_pending_by_root_session("session-cancel"),
            1,
        )
        self.assertIsNone(
            await service.resolve_request(
                pending.request_id,
                ApprovalDecision.APPROVED,
            ),
        )

        state_path = Path(self.tmpdir.name) / "agentteams-hitl.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["records"][pending.request_id]["status"],
            "cancelled",
        )

    async def test_timeout_is_durable_and_does_not_revive(self) -> None:
        os.environ["AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS"] = "0.05"
        service = await self._new_service()
        pending = await service.create_pending_summary(
            session_id="session-2",
            root_session_id="session-2",
            owner_agent_id="default",
            user_id="@human:example",
            channel="",
            agent_id="default",
            summary=self._summary(),
        )

        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        decision = await service.wait_for_approval(
            pending.request_id,
            timeout_seconds=0.05,
        )
        self.assertEqual(decision, ApprovalDecision.TIMEOUT)

        restarted = await self._new_service()
        self.assertIsNone(await restarted.get_request(pending.request_id))

        state_path = Path(self.tmpdir.name) / "agentteams-hitl.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["records"][pending.request_id]["status"],
            "timeout",
        )

    async def test_driver_notification_retries_without_channel_instance(self) -> None:
        os.environ["AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS"] = "1"
        service = await self._new_service()
        channel = _ApprovalChannel()
        manager = _FlakyChannelManager(channel)
        service.set_channel_manager(manager, agent_id="default")

        pending = await service.create_pending_summary(
            session_id="session-3",
            root_session_id="session-3",
            owner_agent_id="default",
            user_id="@human:example",
            channel="agentteams_matrix",
            agent_id="default",
            summary=self._summary(),
        )

        for _ in range(20):
            if channel.notifications:
                break
            await asyncio.sleep(0.02)

        self.assertGreaterEqual(manager.attempts, 2)
        self.assertEqual(len(channel.notifications), 1)
        self.assertEqual(
            channel.notifications[0]["request_id"],
            pending.request_id,
        )

        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        await service.resolve_request(
            pending.request_id,
            ApprovalDecision.DENIED,
        )
