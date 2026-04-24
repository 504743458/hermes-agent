"""Regression tests for gateway dangerous-command text fallback."""

import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import SendResult
from gateway.session import SessionSource


class _ApprovalRequestingAgent:
    last_init = None

    def __init__(self, *args, **kwargs):
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(self, user_message, conversation_history=None, task_id=None, persist_user_message=None):
        from tools import approval as approval_mod

        session_key = type(self).last_init["gateway_session_key"]
        notify = approval_mod._gateway_notify_cbs[session_key]
        notify(
            {
                "command": "rm -rf /important",
                "description": "dangerous command",
            }
        )
        return {
            "final_response": "ok",
            "messages": [],
            "api_calls": 1,
            "completed": True,
        }


def _install_fake_agent(monkeypatch):
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _ApprovalRequestingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)


class _FallbackAdapter:
    platform = Platform.TELEGRAM

    def __init__(self):
        self._send = AsyncMock()
        self._send_exec_approval = AsyncMock(
            return_value=SendResult(success=False, error="callback auth unavailable")
        )
        self.pause_typing_for_chat = MagicMock()

    async def send(self, *args, **kwargs):
        return await self._send(*args, **kwargs)

    async def send_exec_approval(self, *args, **kwargs):
        return await self._send_exec_approval(*args, **kwargs)

    def get_pending_message(self, session_key):
        return None

    def has_pending_interrupt(self, session_key):
        return False

    async def edit_message(self, *args, **kwargs):
        return SendResult(success=False, error="editing not supported")


def _make_runner(adapter):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {adapter.platform: adapter}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._service_tier = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._running_agents = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(streaming=None)
    runner.session_store = SimpleNamespace(_entries={})
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._enrich_message_with_vision = AsyncMock(return_value="hello")
    runner._enforce_agent_cache_cap = lambda: None
    return runner


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="12345",
        chat_type="dm",
        user_id="111",
    )


@pytest.mark.asyncio
async def test_run_agent_falls_back_to_plain_text_when_button_approval_send_fails(monkeypatch, tmp_path):
    _install_fake_agent(monkeypatch)
    adapter = _FallbackAdapter()
    runner = _make_runner(adapter)

    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(gateway_run, "_env_path", tmp_path / ".env")
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "gpt-5.4")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "***",
        },
    )

    import hermes_cli.tools_config as tools_config

    monkeypatch.setattr(tools_config, "_get_platform_tools", lambda user_config, platform_key: {"core"})

    result = await runner._run_agent(
        message="hi",
        context_prompt="",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:telegram:dm:12345",
    )

    assert result["final_response"] == "ok"
    assert adapter._send_exec_approval.await_count == 1
    assert adapter._send.await_count >= 1
    sent_messages = [str(call) for call in adapter._send.call_args_list]
    assert any("Dangerous command requires approval" in item and "/approve" in item for item in sent_messages)
