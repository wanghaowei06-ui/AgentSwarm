#!/usr/bin/env python3
"""Focused Matrix mention contract tests for the native TeamHarness message path."""

from __future__ import annotations

import pathlib
import sys
import unittest


MCP_DIR = pathlib.Path(__file__).resolve().parents[3] / "teamharness" / "mcp"
sys.path.insert(0, str(MCP_DIR))

from message_tool import MessageToolDeps, message  # noqa: E402
from server import _matrix_target, _mentions, _matrix_content  # noqa: E402


class MatrixMentionContractTests(unittest.TestCase):
    """These tests use local fixtures only; they are not LIVE evidence."""

    def test_native_message_qualifies_bare_callback_values(self) -> None:
        """The final native Matrix content boundary must emit complete MXIDs."""

        deps = MessageToolDeps(
            reply_route=lambda _arguments: {},
            qwenpaw_message=lambda *_arguments: {},
            matrix_target=_matrix_target,
            # Fixture for the malformed upstream value observed in M1.
            mentions=lambda _text, _room_id: ["worker-alpha"],
            ping_pong_error=lambda _text, _mentions: None,
            matrix_content=_matrix_content,
            record_matrix_outbound_to_session=lambda *_arguments: True,
        )

        result = message(
            {
                "action": "send",
                "channel": "matrix",
                "target": "room:!task-room:matrix.local",
                "message": "TASK_ASSIGNED: worker-alpha",
                "dryRun": True,
            },
            deps,
        )

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(
            result["content"]["m.mentions"],
            {"user_ids": ["@worker-alpha:matrix.local"]},
        )

    def test_text_short_mention_uses_target_room_server(self) -> None:
        self.assertEqual(
            _mentions("@worker-alpha TASK_ASSIGNED", "!task-room:matrix.local"),
            ["@worker-alpha:matrix.local"],
        )


if __name__ == "__main__":
    unittest.main()
