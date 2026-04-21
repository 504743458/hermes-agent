import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))


class TestBrowserSearchQualityHelpers:
    def test_engine_specs_expose_primary_and_fallback_engines(self):
        from tools.web_tools import _get_browser_search_engine_specs

        specs = _get_browser_search_engine_specs()

        assert [spec["name"] for spec in specs] == ["bing", "duckduckgo_html", "duckduckgo_lite"]
        assert all("url_template" in spec for spec in specs)

    def test_bing_script_targets_result_blocks(self):
        from tools.web_tools import _browser_search_eval_script

        script = _browser_search_eval_script("bing", 5)

        assert "b_algo" in script
        assert ".b_caption" in script

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

    def test_locale_scoring_penalizes_cjk_for_ascii_query(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "example. com邮箱如何注册？_百度知道",
                "url": "https://zhidao.baidu.com/question/123",
                "description": "example.com 邮箱如何注册。",
            },
            {
                "title": "Example Domain",
                "url": "https://example.com/",
                "description": "This domain is for use in documentation examples.",
            },
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Example Domain",
        )

        assert results
        assert results[0]["url"] == "https://example.com/"

    def test_query_relevance_prefers_term_overlap(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "What does colon equal (:=) in Python mean? - Stack Overflow",
                "url": "https://stackoverflow.com/questions/26000198/what-does-colon-equal-in-python-mean",
                "description": "General Python syntax explanation.",
            },
            {
                "title": "Python asyncio tutorial",
                "url": "https://realpython.com/async-io-python/",
                "description": "Learn asyncio and event loops in Python.",
            },
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Python asyncio tutorial",
        )

        assert results[0]["url"] == "https://realpython.com/async-io-python/"

    def test_tutorial_intent_filters_stackoverflow_noise(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "What does colon equal (:=) in Python mean? - Stack Overflow",
                "url": "https://stackoverflow.com/questions/26000198/what-does-colon-equal-in-python-mean",
                "description": "General Python syntax explanation.",
            }
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Python asyncio tutorial",
        )

        assert results == []

    def test_github_intent_prefers_github_domain(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "Hermes Agent Documentation | Hermes Agent",
                "url": "https://hermes-agent.nousresearch.com/docs/",
                "description": "Official docs.",
            },
            {
                "title": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "GitHub repository.",
            },
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Hermes Agent GitHub",
        )

        assert results[0]["url"] == "https://github.com/nousresearch/hermes-agent"

    def test_filters_generic_google_support_noise(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "Browse in Incognito mode - Computer - Google Chrome Help",
                "url": "https://support.google.com/chrome/answer/95464?hl=en",
                "description": "Google support article.",
            },
            {
                "title": "Example Domain",
                "url": "https://example.com/",
                "description": "This domain is for use in documentation examples.",
            },
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Example Domain",
        )

        assert results[0]["url"] == "https://example.com/"

    def test_snapshot_results_can_enrich_existing_candidates(self):
        from tools.web_tools import _merge_browser_search_results

        primary = [
            {
                "title": "GitHub - NousResearch/hermes-agent",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "",
                "position": 1,
            }
        ]
        snapshot = [
            {
                "title": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "The self-improving AI agent built by Nous Research.",
                "position": 1,
            }
        ]

        merged = _merge_browser_search_results(primary, snapshot, limit=5)

        assert len(merged) == 1
        assert merged[0]["description"].startswith("The self-improving AI agent")
        assert "grows with you" in merged[0]["title"]

    def test_weak_results_include_off_topic_matches(self):
        from tools.web_tools import _browser_search_results_are_weak

        results = [
            {
                "title": "What does colon equal (:=) in Python mean? - Stack Overflow",
                "url": "https://stackoverflow.com/questions/26000198/what-does-colon-equal-in-python-mean",
                "description": "General Python syntax explanation.",
                "position": 1,
            }
        ]

        assert _browser_search_results_are_weak(results, 3, query="Python asyncio tutorial") is True

    def test_merge_can_preserve_source_lineage(self):
        from tools.web_tools import _merge_browser_search_results

        primary = [
            {
                "title": "GitHub - NousResearch/hermes-agent",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "",
                "position": 1,
                "_source": "dom",
            }
        ]
        snapshot = [
            {
                "title": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                "url": "https://github.com/nousresearch/hermes-agent",
                "description": "The self-improving AI agent built by Nous Research.",
                "position": 1,
                "_source": "snapshot",
            }
        ]

        merged = _merge_browser_search_results(primary, snapshot, limit=5)

        assert merged[0]["_source"] == "merged"

    def test_normalized_candidates_preserve_source_metadata(self):
        from tools.web_tools import _normalize_browser_search_candidates

        candidates = [
            {
                "title": "Example Domain",
                "url": "https://example.com/",
                "description": "This domain is for use in documentation examples.",
                "_source": "dom",
                "_engine": "bing",
                "_query_variant": "Example Domain",
            }
        ]

        results = _normalize_browser_search_candidates(
            candidates,
            engine="bing",
            limit=5,
            query="Example Domain",
        )

        assert results[0]["_source"] == "dom"
        assert results[0]["_engine"] == "bing"
        assert results[0]["_query_variant"] == "Example Domain"


class TestBrowserSearchQueryVariants:
    def test_github_query_adds_repo_focused_retry(self):
        from tools.web_tools import _build_browser_search_query_variants

        variants = _build_browser_search_query_variants("Hermes Agent GitHub")

        assert variants[0] == "Hermes Agent GitHub"
        assert any("site:github.com" in variant for variant in variants[1:])

    def test_technical_query_adds_docs_retry(self):
        from tools.web_tools import _build_browser_search_query_variants

        variants = _build_browser_search_query_variants("Python asyncio tutorial")

        assert variants[0] == "Python asyncio tutorial"
        assert any("documentation" in variant.lower() or "docs" in variant.lower() for variant in variants[1:])


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

    def test_browser_search_tries_query_variants_before_switching_engines(self):
        weak = {"success": True, "data": {"web": []}}
        strong = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Python asyncio docs",
                        "url": "https://docs.python.org/3/library/asyncio.html",
                        "description": "asyncio library reference",
                        "position": 1,
                    }
                ]
            },
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._query_browser_search_engine",
                side_effect=[weak, weak, strong],
            ) as query_engine,
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("Python asyncio tutorial", limit=3))

        assert result["data"]["web"][0]["url"] == "https://docs.python.org/3/library/asyncio.html"
        first_query = query_engine.call_args_list[0].args[1]
        second_query = query_engine.call_args_list[1].args[1]
        third_query = query_engine.call_args_list[2].args[1]
        assert first_query == "Python asyncio tutorial"
        assert second_query == first_query
        assert third_query != first_query

    def test_browser_search_stops_when_time_budget_is_exhausted(self):
        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch("tools.web_tools._query_browser_search_engine", return_value={"success": True, "data": {"web": []}}) as query_engine,
            patch("tools.web_tools.time.monotonic", side_effect=[0.0, 0.0, 20.0, 20.0, 20.0, 20.0, 20.0]),
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("Example Domain", limit=3))

        assert result["data"]["web"] == []
        assert query_engine.call_count == 1

    def test_browser_search_retries_primary_query_once_on_transient_failure(self):
        strong = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                        "url": "https://github.com/nousresearch/hermes-agent",
                        "description": "Official repository",
                        "position": 1,
                    }
                ]
            },
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._query_browser_search_engine",
                side_effect=[RuntimeError("transient browser failure"), strong],
            ) as query_engine,
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("Hermes Agent GitHub", limit=5))

        assert result["data"]["web"][0]["url"] == "https://github.com/nousresearch/hermes-agent"
        assert query_engine.call_args_list[0].args[1] == "Hermes Agent GitHub"
        assert query_engine.call_args_list[1].args[1] == "Hermes Agent GitHub"

    def test_browser_search_retries_primary_query_once_on_empty_results(self):
        empty = {"success": True, "data": {"web": []}}
        strong = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub",
                        "url": "https://github.com/nousresearch/hermes-agent",
                        "description": "Official repository",
                        "position": 1,
                    }
                ]
            },
        }

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}),
            patch("tools.web_tools._get_firecrawl_client", side_effect=AssertionError("firecrawl should not run")),
            patch("tools.browser_tool.check_browser_requirements", return_value=True),
            patch(
                "tools.web_tools._query_browser_search_engine",
                side_effect=[empty, strong],
            ) as query_engine,
            patch("tools.interrupt.is_interrupted", return_value=False),
        ):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("Hermes Agent GitHub", limit=5))

        assert result["data"]["web"][0]["url"] == "https://github.com/nousresearch/hermes-agent"
        assert query_engine.call_args_list[0].args[1] == "Hermes Agent GitHub"
        assert query_engine.call_args_list[1].args[1] == "Hermes Agent GitHub"
