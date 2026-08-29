"""Tests for the Telnyx call-approval inline buttons (callreq: callbacks).

End-to-end against the REAL machinery, no network: the adapter's
_handle_callback_query dispatches callreq: taps to
_handle_call_request_callback, which runs the skill's real
decide_call_request.py as a subprocess against a real store file in
tmp_path. Assertions read the store and audit log written by the skill's
own _call_approval_store module.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root and the skill's scripts dir are importable
# ---------------------------------------------------------------------------
_repo = Path(__file__).resolve().parents[2]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))
_scripts = _repo / "skills" / "communication" / "telnyx-voice-sms" / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))


# ---------------------------------------------------------------------------
# Minimal Telegram mock so TelegramAdapter can be imported
# (same shim as test_telegram_approval_buttons.py)
# ---------------------------------------------------------------------------
def _ensure_telegram_mock():
    if "telegram" in sys.modules and hasattr(sys.modules["telegram"], "__file__"):
        return

    mod = MagicMock()
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants.ParseMode.MARKDOWN = "Markdown"
    mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    mod.constants.ParseMode.HTML = "HTML"
    mod.constants.ChatType.PRIVATE = "private"
    mod.constants.ChatType.GROUP = "group"
    mod.constants.ChatType.SUPERGROUP = "supergroup"
    mod.constants.ChatType.CHANNEL = "channel"
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})

    for name in ("telegram", "telegram.ext", "telegram.constants", "telegram.request"):
        sys.modules.setdefault(name, mod)
    sys.modules.setdefault("telegram.error", mod.error)


_ensure_telegram_mock()

from plugins.platforms.telegram.adapter import TelegramAdapter  # noqa: E402
from gateway.config import PlatformConfig  # noqa: E402

import _call_approval_store as cas  # noqa: E402


def _make_adapter():
    config = PlatformConfig(enabled=True, token="test-token", extra={})
    adapter = TelegramAdapter(config)
    adapter._bot = AsyncMock()
    adapter._app = MagicMock()
    return adapter


def _make_query(data, user_id="111", first_name="Fernando",
                text="Pedido de ligacao (aprovacao necessaria)"):
    query = AsyncMock()
    query.data = data
    query.message = MagicMock()
    query.message.chat_id = 12345
    query.message.text = text
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.from_user.first_name = first_name
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return query, update


@pytest.fixture
def approval_env(tmp_path):
    """Real store + audit under tmp_path, decide script resolved from repo."""
    env = {
        "TELNYX_CALL_APPROVAL_STORE_PATH": str(tmp_path / "store.json"),
        "TELNYX_CALL_APPROVAL_AUDIT_PATH": str(tmp_path / "audit.jsonl"),
        "TELNYX_CALL_APPROVAL_DECIDE_SCRIPT": str(_scripts / "decide_call_request.py"),
        "TELEGRAM_ALLOWED_USERS": "111",
    }
    with patch.dict(os.environ, env, clear=False):
        yield {k: os.environ[k] for k in env}


def _store_env(approval_env):
    return {
        "TELNYX_CALL_APPROVAL_STORE_PATH": approval_env["TELNYX_CALL_APPROVAL_STORE_PATH"],
        "TELNYX_CALL_APPROVAL_AUDIT_PATH": approval_env["TELNYX_CALL_APPROVAL_AUDIT_PATH"],
    }


def _create_request(approval_env, **kwargs):
    defaults = dict(
        contact="Fornecedor Solar LLC",
        to="+13055551234",
        purpose="Cotar 40 paineis para a obra de Orlando",
        message="Ola, ligo em nome da Axtro para cotar 40 paineis.",
        env=_store_env(approval_env),
    )
    defaults.update(kwargs)
    return cas.create_request(**defaults)


def _audit_events(approval_env):
    path = Path(approval_env["TELNYX_CALL_APPROVAL_AUDIT_PATH"])
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestCallRequestApproveButton:
    @pytest.mark.asyncio
    async def test_approve_tap_records_decision_in_real_store(self, approval_env):
        adapter = _make_adapter()
        req = _create_request(approval_env)
        query, update = _make_query(f"callreq:a:{req['id']}")

        await adapter._handle_callback_query(update, MagicMock())

        stored = cas.get_request(req["id"], env=_store_env(approval_env))
        assert stored["status"] == "approved"
        assert stored["decided_by"] == "111"
        assert stored["decided_by_name"] == "Fernando"
        assert stored["decided_at"] is not None
        # The tap itself never dials: no execution claim exists.
        assert stored["execution"] is None

        events = [e["event"] for e in _audit_events(approval_env)]
        assert "approved" in events

        query.answer.assert_called_once()
        assert "Aprovado" in query.answer.call_args[1]["text"]
        # Keyboard stripped so the button cannot fire twice.
        edit_kwargs = query.edit_message_text.call_args[1]
        assert edit_kwargs["reply_markup"] is None
        assert "Aprovado por Fernando" in edit_kwargs["text"]

    @pytest.mark.asyncio
    async def test_reject_tap_records_rejection(self, approval_env):
        adapter = _make_adapter()
        req = _create_request(approval_env)
        query, update = _make_query(f"callreq:r:{req['id']}")

        await adapter._handle_callback_query(update, MagicMock())

        stored = cas.get_request(req["id"], env=_store_env(approval_env))
        assert stored["status"] == "rejected"
        assert stored["execution"] is None
        assert "Rejeitado" in query.answer.call_args[1]["text"]
        edit_kwargs = query.edit_message_text.call_args[1]
        assert edit_kwargs["reply_markup"] is None

    @pytest.mark.asyncio
    async def test_double_tap_is_idempotent(self, approval_env):
        adapter = _make_adapter()
        req = _create_request(approval_env)

        query1, update1 = _make_query(f"callreq:a:{req['id']}")
        await adapter._handle_callback_query(update1, MagicMock())

        # Second tap (replayed callback / double tap), even trying to flip
        # the decision, changes nothing.
        query2, update2 = _make_query(f"callreq:r:{req['id']}")
        await adapter._handle_callback_query(update2, MagicMock())

        stored = cas.get_request(req["id"], env=_store_env(approval_env))
        assert stored["status"] == "approved"
        assert "ja foi resolvido" in query2.answer.call_args[1]["text"]
        query2.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_late_tap_expires_instead_of_approving(self, approval_env):
        adapter = _make_adapter()
        req = _create_request(approval_env, timeout_seconds=-1)
        query, update = _make_query(f"callreq:a:{req['id']}")

        await adapter._handle_callback_query(update, MagicMock())

        stored = cas.get_request(req["id"], env=_store_env(approval_env))
        assert stored["status"] == "expired"
        assert "expirou" in query.answer.call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_unauthorized_user_cannot_decide(self, approval_env):
        adapter = _make_adapter()
        req = _create_request(approval_env)
        query, update = _make_query(f"callreq:a:{req['id']}",
                                    user_id="666", first_name="Mallory")

        await adapter._handle_callback_query(update, MagicMock())

        stored = cas.get_request(req["id"], env=_store_env(approval_env))
        assert stored["status"] == "pending"
        assert "nao esta autorizado" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_request_id(self, approval_env):
        adapter = _make_adapter()
        query, update = _make_query("callreq:a:cr00000000")

        await adapter._handle_callback_query(update, MagicMock())

        assert "nao encontrado" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_callback_data_is_rejected(self, approval_env):
        adapter = _make_adapter()
        for bad in ("callreq:a:", "callreq:x:cr1", "callreq:a:../../etc/passwd"):
            query, update = _make_query(bad)
            await adapter._handle_callback_query(update, MagicMock())
            assert "Invalid" in query.answer.call_args[1]["text"]
            query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_callback_prefixes_unaffected(self, approval_env):
        """ea: approval callbacks still route to the exec-approval path."""
        adapter = _make_adapter()
        adapter._approval_state[1] = "some-session"
        query, update = _make_query("ea:once:1")

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "*"}):
                await adapter._handle_callback_query(update, MagicMock())

        mock_resolve.assert_called_once_with("some-session", "once")
