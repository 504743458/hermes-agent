import json
import os
import sys
import types
from unittest.mock import patch

sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))


class TestBrowserSearchQualityHelpers:
    def test_unwraps_bing_redirect_url(self):
        from tools.web_tools import _unwrap_browser_search_url

        raw = (
            "https://www.bing.com/ck/a?!&&p=abc123&u="
            "a1aHR0cHM6Ly9leGFtcGxlLmNvbS9kb2Nz&ntb=1"
        )

        assert _unwrap_browser_search_url(raw) == "https://example.com/docs"

    def test_filters_engine_navigation_links(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "全部",
                "url": "https://www.bing.com/search?q=example",
                "description": "bing nav",
            },
            {
                "title": "Example Domain",
                "url": "https://example.com/",
                "description": "This domain is for use in documentation examples.",
            },
        ]

        results = _normalize_browser_search_candidates(candidates, engine="bing", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Example Domain"

    def test_strips_breadcrumb_prefixes_from_titles_and_descriptions(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "github.comhttps://github.com › nousresearch › hermes-agent",
                "heading": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "github.comhttps://github.com › nousresearch › hermes-agent The self-improving AI agent built by Nous Research.",
            }
        ]

        results = _normalize_browser_search_candidates(candidates, engine="bing", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub"
        assert results[0]["description"].startswith("The self-improving AI agent")

    def test_snapshot_fallback_maps_titles_to_links(self):
        from tools.web_tools import _extract_search_results_from_snapshot

        snapshot = """- main
  - list
    - listitem
      - heading "Example Domain" [level=2]
      - paragraph
        - StaticText "This domain is for use in documentation examples."
"""
        anchors = [
            {
                "title": "Example Domain",
                "url": "https://example.com/",
                "description": "",
            }
        ]

        results = _extract_search_results_from_snapshot(snapshot, anchors, limit=3)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/"
        assert "documentation examples" in results[0]["description"]


class TestBrowserSearchEngineSelection:
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

    def test_browser_search_tries_secondary_engine_when_primary_is_weak(self):
        weak = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "搜索",
                        "url": "https://www.bing.com/search?q=hermes",
                        "description": "bing nav",
                        "position": 1,
                    }
                ]
            },
        }
        strong = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Hermes Agent Docs",
                        "url": "https://example.com/docs",
                        "description": "Official docs",
                        "position": 1,
                    },
                    {
                        "title": "Hermes Agent GitHub",
                        "url": "https://example.com/repo",
                        "description": "Source code",
                        "position": 2,
                    },
                ]
            },
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._query_browser_search_engine",
                side_effect=[weak, strong],
            ),
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("hermes agent", limit=2))

        assert len(result["data"]["web"]) == 2
        assert result["data"]["web"][0]["title"] == "Hermes Agent Docs"
