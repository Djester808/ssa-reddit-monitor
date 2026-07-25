"""Tests for ssa_dashboard.py order parsing and matching functions."""

import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import helpers — load modules without executing their __main__ blocks
# ---------------------------------------------------------------------------

def _load(path):
    spec = importlib.util.spec_from_file_location("_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Stub tkinter before importing dashboard so tests run headless
tk_stub = types.ModuleType("tkinter")
for cls in ["Tk", "Toplevel", "Frame", "Label", "Button", "Entry", "Radiobutton", "Text"]:
    setattr(tk_stub, cls, object)
tk_stub.StringVar = MagicMock(return_value=MagicMock(trace_add=lambda *a, **k: None, get=lambda: ""))
tk_stub.ttk = types.ModuleType("tkinter.ttk")
tk_stub.ttk.Style = MagicMock()
tk_stub.ttk.Treeview = MagicMock()
tk_stub.ttk.Scrollbar = MagicMock()
tk_stub.ttk.Progressbar = MagicMock()
mb_stub = types.ModuleType("tkinter.messagebox")
mb_stub.showinfo = MagicMock()
mb_stub.showerror = MagicMock()
tk_stub.messagebox = mb_stub
sys.modules.setdefault("tkinter", tk_stub)
sys.modules.setdefault("tkinter.ttk", tk_stub.ttk)
sys.modules.setdefault("tkinter.messagebox", mb_stub)

dashboard = _load(os.path.join(PROJECT_DIR, "ssa_dashboard.py"))


# ---------------------------------------------------------------------------
# parse_order_input
# ---------------------------------------------------------------------------

class TestParseOrderInput:
    def test_quantity_with_x(self):
        """Parse '2x product name'"""
        items = dashboard.parse_order_input("2x orange juice")
        assert len(items) == 1
        assert items[0] == (2, "orange juice")

    def test_quantity_with_capital_x(self):
        """Parse '2X product name' (capital X)"""
        items = dashboard.parse_order_input("2X orange juice")
        assert len(items) == 1
        assert items[0] == (2, "orange juice")

    def test_default_quantity_one(self):
        """Product without quantity defaults to 1"""
        items = dashboard.parse_order_input("orange juice")
        assert len(items) == 1
        assert items[0] == (1, "orange juice")

    def test_multiline_input(self):
        """Parse multiple lines"""
        text = "2x orange juice\n3x sponge filter\napple leaf"
        items = dashboard.parse_order_input(text)
        assert len(items) == 3
        assert (2, "orange juice") in items
        assert (3, "sponge filter") in items
        assert (1, "apple leaf") in items

    def test_mixed_case_x(self):
        """Handle both 'x' and 'X' in same input"""
        text = "2x apricorn\n3X blue dream"
        items = dashboard.parse_order_input(text)
        assert (2, "apricorn") in items
        assert (3, "blue dream") in items

    def test_empty_lines_ignored(self):
        """Skip empty lines"""
        text = "2x orange juice\n\n3x sponge filter"
        items = dashboard.parse_order_input(text)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# fuzzy_match_product
# ---------------------------------------------------------------------------

class TestFuzzyMatchProduct:
    @pytest.fixture
    def products(self):
        """Sample product list for testing"""
        return [
            {"title": "Orange Juice (Rotala Rotundifolia 'Orange Juice')", "id": "1"},
            {"title": "Jungle Vallisneria (Vallisneria americana)", "id": "2"},
            {"title": "Sponge Filter", "id": "3"},
            {"title": "Sinking Moss Ball", "id": "4"},
            {"title": "Blue Dream Neocaridina", "id": "5"},
        ]

    def test_exact_match_partial(self, products):
        """Match on partial product name"""
        matches = dashboard.fuzzy_match_product("orange juice", products)
        assert len(matches) > 0
        assert any("Orange Juice" in m[0]["title"] for m in matches)

    def test_jungle_vallisneria(self, products):
        """Jungle Vallisneria should match 'jungle val'"""
        matches = dashboard.fuzzy_match_product("jungle val", products)
        assert len(matches) > 0
        assert any("Jungle Vallisneria" in m[0]["title"] for m in matches)

    def test_case_insensitive(self, products):
        """Matching should be case-insensitive"""
        matches = dashboard.fuzzy_match_product("BLUE DREAM", products)
        assert len(matches) > 0
        assert any("Blue Dream" in m[0]["title"] for m in matches)

    def test_no_match_returns_empty(self, products):
        """No match returns empty list"""
        matches = dashboard.fuzzy_match_product("xyz123nonexistent", products)
        assert matches == []

    def test_threshold_enforcement(self, products):
        """Scores below threshold return empty list"""
        # Very similar threshold should only accept close matches
        matches = dashboard.fuzzy_match_product("xyz", products, threshold=0.9)
        assert matches == []

    def test_sponge_filter_over_moss(self, products):
        """Exact 'sponge filter' should rank Sponge Filter highly"""
        matches = dashboard.fuzzy_match_product("sponge filter", products)
        assert len(matches) > 0
        # First match should be the Sponge Filter
        assert matches[0][0]["title"] == "Sponge Filter"
