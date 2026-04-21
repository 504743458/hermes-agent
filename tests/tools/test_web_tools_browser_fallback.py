import asyncio
import json
import os
import sys
import types
from unittest.mock import patch

sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))


class TestBrowserBackedWebFallback:
    _ENV_KEYS = (
        "EXA_API_KEY",
        "PARALLEL_API_KEY",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "FIRECRAWL_GATEWAY_URL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
        "TAVILY_API_KEY",
    )

    def setup_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def test_check_web_tool_available_accepts_browser_fallback_without_api_backend(self):
        with patch("tools.browser_tool.check_browser_requirements", return_value=True):
            from tools.web_tools import check_web_tool_available

            assert check_web_tool_available() is True

    def test_web_search_falls_back_to_browser_when_backend_unavailable(self):
        browser_results = {
            "success": True,
            "result": [
                {
                    "title": "Hermes Agent Docs",
                    "url": "https://example.com/docs",
                    "description": "Official documentation",
                },
                {
                    "title": "Hermes Agent GitHub",
                    "url": "https://example.com/repo",
                    "description": "Source repository",
                },
            ],
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._run_agent_browser_json",
                side_effect=[
                    {"success": True, "data": {"url": "https://duckduckgo.com/html/?q=hermes+agent"}},
                    {"success": True, "data": browser_results},
                    {"success": True, "data": {"closed": True}},
                ],
            ),
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("hermes agent", limit=2))

        assert result["success"] is True
        assert len(result["data"]["web"]) == 2
        assert result["data"]["web"][0]["title"] == "Hermes Agent Docs"
        assert result["data"]["web"][0]["url"] == "https://example.com/docs"

    def test_web_extract_falls_back_to_browser_when_backend_unavailable(self):
        browser_extract = {
            "success": True,
            "result": {
                "url": "https://example.com/page",
                "title": "Example Page",
                "content": "Extracted page body",
            },
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.web_tools.check_auxiliary_model", return_value=False),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._run_agent_browser_json",
                side_effect=[
                    {"success": True, "data": {"url": "https://example.com/page", "title": "Example Page"}},
                    {"success": True, "data": browser_extract},
                    {"success": True, "data": {"closed": True}},
                ],
            ),
        ):
            from tools.web_tools import web_extract_tool

            result = json.loads(
                asyncio.get_event_loop().run_until_complete(
                    web_extract_tool(["https://example.com/page"], use_llm_processing=False)
                )
            )

        assert result["results"][0]["url"] == "https://example.com/page"
        assert result["results"][0]["title"] == "Example Page"
        assert result["results"][0]["content"] == "Extracted page body"
        assert result["results"][0]["error"] is None
