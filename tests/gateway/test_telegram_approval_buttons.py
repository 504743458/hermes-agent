"""Tests for Telegram inline keyboard approval buttons."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is importable
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Minimal Telegram mock so TelegramAdapter can be imported
# ---------------------------------------------------------------------------
def _ensure_telegram_mock():
    """Wire up the minimal mocks required to import TelegramAdapter."""
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
    # Provide real exception classes so ``except (NetworkError, ...)`` in
    # connect() doesn't blow up under xdist when this mock leaks.
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})

    for name in ("telegram", "telegram.ext", "telegram.constants", "telegram.request"):
        sys.modules.setdefault(name, mod)
    sys.modules.setdefault("telegram.error", mod.error)


_ensure_telegram_mock()

from gateway.platforms.telegram import TelegramAdapter
from gateway.config import Platform, PlatformConfig


def _make_adapter(extra=None):
    """Create a TelegramAdapter with mocked internals."""
    config = PlatformConfig(enabled=True, token="test-token", extra=extra or {})
    adapter = TelegramAdapter(config)
    adapter._bot = AsyncMock()
    adapter._app = MagicMock()
    return adapter


class _AuthRunner:
    """Minimal runner shim for callback auth tests."""

    def __init__(self, authorized: bool):
        self.authorized = authorized
        self.last_source = None

    async def _handle_message(self, event):
        return None

    def _is_user_authorized(self, source):
        self.last_source = source
        return self.authorized


def _approval_state(session_key="agent:main:telegram:group:12345:99", chat_id="12345",
                    message_id="42", expected_user_id=""):
    return {
        "session_key": session_key,
        "chat_id": chat_id,
        "message_id": message_id,
        "expected_user_id": expected_user_id,
        "expires_at": 4_102_444_800,
    }


def _update_prompt_state(chat_id="12345", session_key="agent:main:telegram:dm:12345",
                         message_id="77", update_token="update-1", expected_user_id=""):
    return {
        "chat_id": chat_id,
        "session_key": session_key,
        "message_id": message_id,
        "expected_user_id": expected_user_id,
        "update_token": update_token,
        "expires_at": 4_102_444_800,
    }


def _write_update_pending(tmp_path, chat_id="12345", session_key="agent:main:telegram:dm:12345",
                          update_token="update-1"):
    (tmp_path / ".update_pending.json").write_text(
        json.dumps({
            "platform": "telegram",
            "chat_id": chat_id,
            "session_key": session_key,
            "timestamp": update_token,
        }),
        encoding="utf-8",
    )


# ===========================================================================
# send_exec_approval — inline keyboard buttons
# ===========================================================================

class TestTelegramExecApproval:
    """Test the send_exec_approval method sends InlineKeyboard buttons."""

    @pytest.mark.asyncio
    async def test_sends_inline_keyboard(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            result = await adapter.send_exec_approval(
                chat_id="12345",
                command="rm -rf /important",
                session_key="agent:main:telegram:group:12345:99",
                description="dangerous deletion",
            )

        assert result.success is True
        assert result.message_id == "42"

        adapter._bot.send_message.assert_called_once()
        kwargs = adapter._bot.send_message.call_args[1]
        assert kwargs["chat_id"] == 12345
        assert "rm -rf /important" in kwargs["text"]
        assert "dangerous deletion" in kwargs["text"]
        assert kwargs["reply_markup"] is not None  # InlineKeyboardMarkup

    @pytest.mark.asyncio
    async def test_stores_approval_state(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            await adapter.send_exec_approval(
                chat_id="12345",
                command="echo test",
                session_key="my-session-key",
            )

        assert len(adapter._approval_state) == 1
        approval_nonce = list(adapter._approval_state.keys())[0]
        approval_state = adapter._approval_state[approval_nonce]
        assert len(approval_nonce) >= 16
        assert approval_state["session_key"] == "my-session-key"
        assert approval_state["chat_id"] == "12345"
        assert approval_state["message_id"] == "42"

    @pytest.mark.asyncio
    async def test_sends_in_thread(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            await adapter.send_exec_approval(
                chat_id="12345",
                command="ls",
                session_key="s",
                metadata={"thread_id": "999"},
            )

        kwargs = adapter._bot.send_message.call_args[1]
        assert kwargs.get("message_thread_id") == 999

    @pytest.mark.asyncio
    async def test_not_connected(self):
        adapter = _make_adapter()
        adapter._bot = None
        result = await adapter.send_exec_approval(
            chat_id="12345", command="ls", session_key="s"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_exec_approval_returns_failure_without_callback_safe_allowlist(self):
        adapter = _make_adapter()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=False):
                result = await adapter.send_exec_approval(
                    chat_id="12345",
                    command="rm -rf /important",
                    session_key="agent:main:telegram:group:12345:99",
                )

        assert result.success is False
        assert "callback auth" in result.error.lower()
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_update_prompt_returns_failure_without_callback_safe_allowlist(self):
        adapter = _make_adapter()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=False):
                result = await adapter.send_update_prompt(
                    chat_id="12345",
                    prompt="Restore local changes?",
                    default="y",
                )

        assert result.success is False
        assert "callback auth" in result.error.lower()
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_exec_approval_allows_paired_dm_without_allowlist(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=True):
                result = await adapter.send_exec_approval(
                    chat_id="8685028645",
                    command="echo test",
                    session_key="agent:main:telegram:dm:8685028645",
                )

        assert result.success is True
        adapter._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_update_prompt_allows_paired_dm_without_allowlist(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=True):
                result = await adapter.send_update_prompt(
                    chat_id="8685028645",
                    prompt="Restore local changes?",
                    default="y",
                    session_key="agent:main:telegram:dm:8685028645",
                )

        assert result.success is True
        adapter._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_link_previews_sets_preview_kwargs(self):
        adapter = _make_adapter(extra={"disable_link_previews": True})
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            await adapter.send_exec_approval(
                chat_id="12345", command="ls", session_key="s"
            )

        kwargs = adapter._bot.send_message.call_args[1]
        assert (
            kwargs.get("disable_web_page_preview") is True
            or kwargs.get("link_preview_options") is not None
        )

    @pytest.mark.asyncio
    async def test_truncates_long_command(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        long_cmd = "x" * 5000
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            await adapter.send_exec_approval(
                chat_id="12345", command=long_cmd, session_key="s"
            )

        kwargs = adapter._bot.send_message.call_args[1]
        assert "..." in kwargs["text"]
        assert len(kwargs["text"]) < 5000

    def test_callback_user_auth_requires_explicit_allowlist(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=False):
                assert TelegramAdapter._is_callback_user_authorized("111") is False

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111,222"}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=False):
                assert TelegramAdapter._is_callback_user_authorized("111") is True
                assert TelegramAdapter._is_callback_user_authorized("999") is False

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
            with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=True):
                assert TelegramAdapter._is_callback_user_authorized("111") is True


# ===========================================================================
# _handle_callback_query — approval button clicks
# ===========================================================================

class TestTelegramApprovalCallback:
    """Test the approval callback handling in _handle_callback_query."""

    @pytest.mark.asyncio
    async def test_resolves_approval_on_click(self):
        adapter = _make_adapter()
        adapter._approval_state["nonce-a"] = _approval_state()

        query = AsyncMock()
        query.data = "ea:once:nonce-a"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.from_user.first_name = "Norbert"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_called_once_with("agent:main:telegram:group:12345:99", "once")
        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()

        # State should be cleaned up
        assert "nonce-a" not in adapter._approval_state

    @pytest.mark.asyncio
    async def test_deny_button(self):
        adapter = _make_adapter()
        adapter._approval_state["nonce-b"] = _approval_state(session_key="some-session")

        query = AsyncMock()
        query.data = "ea:deny:nonce-b"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.from_user.first_name = "Alice"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_called_once_with("some-session", "deny")
        edit_kwargs = query.edit_message_text.call_args[1]
        assert "Denied" in edit_kwargs["text"]

    @pytest.mark.asyncio
    async def test_approval_callback_rejects_user_blocked_by_global_allowlist(self):
        adapter = _make_adapter()
        adapter._approval_state[7] = "agent:main:telegram:group:12345:99"
        runner = _AuthRunner(authorized=False)
        adapter._message_handler = runner._handle_message

        query = AsyncMock()
        query.data = "ea:once:7"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.chat.type = "private"
        query.from_user = MagicMock()
        query.from_user.id = 222
        query.from_user.first_name = "Mallory"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "not authorized" in query.answer.call_args[1]["text"].lower()
        query.edit_message_text.assert_not_called()
        assert adapter._approval_state[7] == "agent:main:telegram:group:12345:99"
        assert runner.last_source is not None
        assert runner.last_source.platform == Platform.TELEGRAM
        assert runner.last_source.user_id == "222"
        assert runner.last_source.chat_id == "12345"

    @pytest.mark.asyncio
    async def test_already_resolved(self):
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "ea:once:missing-nonce"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.from_user.first_name = "Bob"
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "expired" in query.answer.call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_approval_callback_rejects_wrong_message_context(self):
        adapter = _make_adapter()
        adapter._approval_state["nonce-c"] = _approval_state(message_id="42")

        query = AsyncMock()
        query.data = "ea:once:nonce-c"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 99
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "not valid" in query.answer.call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_approval_callback_rejects_paired_dm_user_mismatch(self):
        adapter = _make_adapter()
        adapter._approval_state["nonce-d"] = _approval_state(
            session_key="agent:main:telegram:dm:12345",
            chat_id="12345",
            expected_user_id="12345",
        )

        query = AsyncMock()
        query.data = "ea:once:nonce-d"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 999
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=True):
            with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "not valid" in query.answer.call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_approval_callback_rejects_after_shutdown_preparation(self):
        adapter = _make_adapter()
        adapter._approval_state["nonce-shutdown"] = _approval_state()
        adapter.prepare_for_shutdown()

        query = AsyncMock()
        query.data = "ea:once:nonce-shutdown"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}, clear=False):
            with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "restarting" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()
        assert adapter._approval_state == {}

    @pytest.mark.asyncio
    async def test_slash_confirm_callback_rejects_after_shutdown_preparation(self):
        adapter = _make_adapter()
        adapter._slash_confirm_state["confirm-shutdown"] = "agent:main:telegram:dm:12345"
        adapter.prepare_for_shutdown()

        query = AsyncMock()
        query.data = "sc:once:confirm-shutdown"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 42
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.slash_confirm.resolve", new_callable=AsyncMock) as mock_resolve:
            await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "restarting" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()
        assert adapter._slash_confirm_state == {}

    @pytest.mark.asyncio
    async def test_model_picker_callback_not_affected(self):
        """Ensure model picker callbacks still route correctly."""
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "mp:some_provider"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        # Model picker callback should be handled (not crash)
        # We just verify it doesn't try to resolve an approval
        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            with patch.object(adapter, "_handle_model_picker_callback", new_callable=AsyncMock):
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_when_allowlist_and_pairing_are_absent(self, tmp_path):
        """Update prompt buttons must not fail open when neither allowlist nor pairing authorizes them."""
        adapter = _make_adapter()
        adapter._update_prompt_state["prompt-a"] = _update_prompt_state()
        _write_update_pending(tmp_path)

        query = AsyncMock()
        query.data = "up:y:prompt-a"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 123
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
                with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
                    with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=False):
                        await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        assert "not authorized" in query.answer.call_args[1]["text"].lower()
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_allows_paired_user_when_allowlist_is_empty(self, tmp_path):
        """A paired Telegram DM user should still be able to click update prompt buttons."""
        adapter = _make_adapter()
        adapter._update_prompt_state["prompt-b"] = _update_prompt_state(
            expected_user_id="12345",
        )
        _write_update_pending(tmp_path)

        query = AsyncMock()
        query.data = "up:y:prompt-b"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 12345
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
                with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}, clear=False):
                    with patch.object(TelegramAdapter, "_is_pairing_approved", return_value=True):
                        await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()
        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        assert (tmp_path / ".update_response").read_text() == "y"

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_legacy_unbound_button(self, tmp_path):
        adapter = _make_adapter()
        _write_update_pending(tmp_path)

        query = AsyncMock()
        query.data = "update_prompt:y"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        assert "expired" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_stale_update_token(self, tmp_path):
        adapter = _make_adapter()
        adapter._update_prompt_state["prompt-stale"] = _update_prompt_state(
            update_token="old-update",
        )
        _write_update_pending(tmp_path, update_token="new-update")

        query = AsyncMock()
        query.data = "up:y:prompt-stale"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        assert "not valid" in query.answer.call_args[1]["text"]
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_unauthorized_user(self, tmp_path):
        """Update prompt buttons should honor TELEGRAM_ALLOWED_USERS."""
        adapter = _make_adapter()
        adapter._update_prompt_state["prompt-c"] = _update_prompt_state()
        _write_update_pending(tmp_path)

        query = AsyncMock()
        query.data = "up:y:prompt-c"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        assert "not authorized" in query.answer.call_args[1]["text"].lower()
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_user_blocked_by_global_allowlist(self, tmp_path):
        adapter = _make_adapter()
        runner = _AuthRunner(authorized=False)
        adapter._message_handler = runner._handle_message

        query = AsyncMock()
        query.data = "update_prompt:y"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.chat.type = "private"
        query.from_user = MagicMock()
        query.from_user.id = 222
        query.from_user.first_name = "Mallory"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        assert "not authorized" in query.answer.call_args[1]["text"].lower()
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()
        assert runner.last_source is not None
        assert runner.last_source.platform == Platform.TELEGRAM
        assert runner.last_source.user_id == "222"

    @pytest.mark.asyncio
    async def test_update_prompt_callback_allows_authorized_user(self, tmp_path):
        """Allowed Telegram users can still answer update prompt buttons."""
        adapter = _make_adapter()
        adapter._update_prompt_state["prompt-d"] = _update_prompt_state()
        _write_update_pending(tmp_path)

        query = AsyncMock()
        query.data = "up:n:prompt-d"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.message_id = 77
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        assert (tmp_path / ".update_response").read_text() == "n"
