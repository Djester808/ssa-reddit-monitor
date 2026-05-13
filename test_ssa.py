"""Tests for ssa_notify.py and ssa_dashboard.py pure functions."""

import importlib.util
import json
import os
import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import helpers — load modules without executing their __main__ blocks
# ---------------------------------------------------------------------------

def _load(path):
    spec = importlib.util.spec_from_file_location("_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

# Stub tkinter before importing dashboard so tests run headless
tk_stub = types.ModuleType("tkinter")
tk_stub.Tk = object
tk_stub.Frame = object
tk_stub.Label = object
tk_stub.Button = object
tk_stub.Entry = object
tk_stub.Radiobutton = object
tk_stub.StringVar = MagicMock(return_value=MagicMock(trace_add=lambda *a, **k: None, get=lambda: ""))
tk_stub.ttk = types.ModuleType("tkinter.ttk")
tk_stub.ttk.Style = MagicMock()
tk_stub.ttk.Treeview = MagicMock()
tk_stub.ttk.Scrollbar = MagicMock()
tk_stub.ttk.Progressbar = MagicMock()
sys.modules.setdefault("tkinter", tk_stub)
sys.modules.setdefault("tkinter.ttk", tk_stub.ttk)

notify   = _load(os.path.join(DOWNLOADS, "ssa_notify.py"))
dashboard = _load(os.path.join(DOWNLOADS, "ssa_dashboard.py"))


# ---------------------------------------------------------------------------
# is_negative
# ---------------------------------------------------------------------------

class TestIsNegative:
    def test_doa_triggers(self):
        assert dashboard.is_negative("shrimp arrived doa :(")

    def test_scam_triggers(self):
        assert dashboard.is_negative("This seller is a total SCAM")

    def test_positive_text_clean(self):
        assert not dashboard.is_negative("Amazing shrimp, all healthy!")

    def test_empty_string(self):
        assert not dashboard.is_negative("")

    def test_case_insensitive(self):
        assert dashboard.is_negative("DEAD on arrival")

    def test_partial_word_match(self):
        # "disease" is in NEG_WORDS; ensure substring match works
        assert dashboard.is_negative("my tank has a disease outbreak")


# ---------------------------------------------------------------------------
# is_own_post
# ---------------------------------------------------------------------------

class TestIsOwnPost:
    def test_djester808(self):
        assert dashboard.is_own_post("djester808")

    def test_superiorshrimpaquatics(self):
        assert dashboard.is_own_post("superiorshrimpaquatics")

    def test_case_insensitive(self):
        assert dashboard.is_own_post("Djester808")

    def test_stranger(self):
        assert not dashboard.is_own_post("some_random_user")

    def test_none(self):
        assert not dashboard.is_own_post(None)

    def test_empty(self):
        assert not dashboard.is_own_post("")


# ---------------------------------------------------------------------------
# fmt_time (dashboard)
# ---------------------------------------------------------------------------

class TestFmtTime:
    def test_none_returns_empty(self):
        assert dashboard.fmt_time(None) == ""

    def test_zero_returns_empty(self):
        assert dashboard.fmt_time(0) == ""

    def test_returns_string_with_timezone(self):
        epoch = 1700000000  # Nov 2023 — CST (no DST)
        result = dashboard.fmt_time(epoch)
        assert result != ""
        assert "CST" in result or "CDT" in result

    def test_format_structure(self):
        epoch = 1700000000
        result = dashboard.fmt_time(epoch)
        # Should look like "2023-11-14 21:13 CST"
        parts = result.split()
        assert len(parts) == 3
        assert len(parts[0]) == 10  # YYYY-MM-DD
        assert ":" in parts[1]      # HH:MM


# ---------------------------------------------------------------------------
# format_dt (notify)
# ---------------------------------------------------------------------------

class TestFormatDt:
    def test_returns_string_with_timezone(self):
        epoch = 1700000000
        result = notify.format_dt(epoch)
        assert "CST" in result or "CDT" in result

    def test_format_structure(self):
        epoch = 1700000000
        result = notify.format_dt(epoch)
        parts = result.split()
        assert len(parts) == 3
        assert len(parts[0]) == 10


# ---------------------------------------------------------------------------
# load_seen / save_seen
# ---------------------------------------------------------------------------

class TestSeenPersistence:
    def test_save_and_reload(self, tmp_path):
        seen_file = tmp_path / "seen_ids.json"
        with patch.object(notify, "SEEN_FILE", str(seen_file)):
            notify.save_seen({"posts": ["abc"], "comments": ["xyz"]})
            result = notify.load_seen()
        assert result["posts"] == ["abc"]
        assert result["comments"] == ["xyz"]

    def test_load_missing_file_returns_empty(self, tmp_path):
        missing = str(tmp_path / "no_such_file.json")
        with patch.object(notify, "SEEN_FILE", missing):
            result = notify.load_seen()
        assert result == {"posts": [], "comments": []}


# ---------------------------------------------------------------------------
# load_results (dashboard)
# ---------------------------------------------------------------------------

class TestLoadResults:
    def test_missing_file_returns_empty_lists(self, tmp_path):
        missing = str(tmp_path / "no_results.json")
        with patch.object(dashboard, "RESULTS_FILE", missing):
            posts, comments = dashboard.load_results()
        assert posts == []
        assert comments == []

    def test_reads_posts_and_comments(self, tmp_path):
        rf = tmp_path / "results_latest.json"
        rf.write_text(json.dumps({
            "posts":    [{"id": "p1", "title": "hello"}],
            "comments": [{"id": "c1", "body": "world"}],
        }))
        with patch.object(dashboard, "RESULTS_FILE", str(rf)):
            posts, comments = dashboard.load_results()
        assert len(posts) == 1
        assert posts[0]["title"] == "hello"
        assert len(comments) == 1


# ---------------------------------------------------------------------------
# fetch_json (notify) — mocked HTTP
# ---------------------------------------------------------------------------

class TestRegisterProtocol:
    def test_runs_without_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            notify.register_protocol()
            mock_run.assert_called_once()
            cmd_arg = mock_run.call_args[0][0]
            assert cmd_arg[0] == "powershell"

    def test_protocol_name_in_script(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            notify.register_protocol()
            ps_script = mock_run.call_args[1]["kwargs"]["command"] if "kwargs" in mock_run.call_args else mock_run.call_args[0][0]
            # The PowerShell command string is the last element
            full_cmd = mock_run.call_args[0][0]
            assert "ssa-monitor" in full_cmd[-1]


class TestFetchJson:
    def test_returns_parsed_json(self):
        payload = json.dumps({"ok": True}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = notify.fetch_json("https://example.com/test.json")
        assert result == {"ok": True}

    def test_retries_on_429(self):
        import urllib.error
        calls = []

        def fake_open(req, timeout):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None)
            payload = json.dumps({"ok": True}).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_open), \
             patch("time.sleep"):
            result = notify.fetch_json("https://example.com/test.json", retries=3)
        assert result == {"ok": True}
        assert len(calls) == 3


# ---------------------------------------------------------------------------
# search_posts / search_comments — mocked fetch_json
# ---------------------------------------------------------------------------

class TestSearchFunctions:
    def _make_listing(self, items):
        return {"data": {"children": [{"data": item} for item in items]}}

    def test_search_posts_global(self):
        listing = self._make_listing([{"id": "p1", "title": "SSA rocks"}])
        with patch.object(notify, "fetch_json", return_value=listing):
            posts = notify.search_posts("superior shrimp aquatics")
        assert len(posts) == 1
        assert posts[0]["title"] == "SSA rocks"

    def test_search_posts_subreddit(self):
        listing = self._make_listing([{"id": "p2", "title": "sub post"}])
        with patch.object(notify, "fetch_json", return_value=listing) as mock_fj:
            notify.search_posts("superior shrimp", subreddit="shrimptank")
            url = mock_fj.call_args[0][0]
        assert "shrimptank" in url
        assert "restrict_sr=on" in url

    def test_search_comments(self):
        listing = self._make_listing([{"id": "c1", "body": "great shrimp"}])
        with patch.object(notify, "fetch_json", return_value=listing):
            comments = notify.search_comments("djester808")
        assert len(comments) == 1

    def test_returns_empty_on_none(self):
        with patch.object(notify, "fetch_json", return_value=None):
            assert notify.search_posts("anything") == []
            assert notify.search_comments("anything") == []
