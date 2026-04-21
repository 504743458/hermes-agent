import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))


class TestSearxngBackendSelection:
    _ENV_KEYS = (
        "SEARXNG_BASE_URL",
        "SEARXNG_API_KEY",
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

    def test_configured_backend_uses_searxng(self):
        with patch("tools.web_tools._load_web_config", return_value={"backend": "searxng"}):
            from tools.web_tools import _get_backend

            assert _get_backend() == "searxng"

    def test_fallback_uses_searxng_when_only_base_url_is_present(self):
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"SEARXNG_BASE_URL": "http://localhost:8080"}):
            from tools.web_tools import _get_backend, check_web_api_key

            assert _get_backend() == "searxng"
            assert check_web_api_key() is True


class TestSearxngSearch:
    _ENV_KEYS = (
        "SEARXNG_BASE_URL",
        "SEARXNG_API_KEY",
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

    def test_searxng_search_normalizes_results(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "url": "https://example.com/docs",
                    "title": "Example Docs",
                    "content": "Documentation result",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "http://localhost:8080"}), \
             patch("tools.web_tools.httpx.get", return_value=mock_response) as mock_get, \
             patch("tools.interrupt.is_interrupted", return_value=False):
            from tools.web_tools import _searxng_search

            result = _searxng_search("example docs", limit=3)

        assert result["success"] is True
        assert result["data"]["web"][0]["title"] == "Example Docs"
        assert result["data"]["web"][0]["url"] == "https://example.com/docs"
        assert mock_get.call_args.kwargs["params"]["q"] == "example docs"
        assert mock_get.call_args.kwargs["params"]["format"] == "json"

    def test_searxng_search_adds_authorization_header_when_api_key_is_present(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(
            os.environ,
            {
                "SEARXNG_BASE_URL": "http://localhost:8080",
                "SEARXNG_API_KEY": "secret-token",
            },
        ), patch("tools.web_tools.httpx.get", return_value=mock_response) as mock_get, \
             patch("tools.interrupt.is_interrupted", return_value=False):
            from tools.web_tools import _searxng_search

            _searxng_search("example docs", limit=3)

        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-token"

    def test_web_search_dispatches_to_searxng_backend(self):
        searxng_result = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Example Docs",
                        "url": "https://example.com/docs",
                        "description": "Documentation result",
                        "position": 1,
                    }
                ]
            },
        }

        with patch("tools.web_tools._load_web_config", return_value={"backend": "searxng"}), \
             patch("tools.web_tools._searxng_search", return_value=searxng_result), \
             patch("tools.interrupt.is_interrupted", return_value=False):
            from tools.web_tools import web_search_tool

            result = json.loads(web_search_tool("example docs", limit=3))

        assert result["success"] is True
        assert result["data"]["web"][0]["url"] == "https://example.com/docs"
