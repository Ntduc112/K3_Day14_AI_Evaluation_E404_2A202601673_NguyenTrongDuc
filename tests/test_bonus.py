"""Additional tests for the optional retrieval-reranking bonus."""

import importlib.util
import sys
from pathlib import Path


SOLUTION_PATH = Path(__file__).parent.parent / "solution" / "solution.py"
SPEC = importlib.util.spec_from_file_location("bonus_solution", SOLUTION_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
rerank_by_overlap = MODULE.rerank_by_overlap


def test_rerank_by_overlap_orders_highest_overlap_first():
    contexts = [
        "Bananas are a tropical fruit rich in potassium.",
        "Paris is the capital city of France in Europe.",
        "France has Paris as its capital.",
    ]

    reranked = rerank_by_overlap(contexts, "What is the capital of France?")

    assert reranked == [contexts[1], contexts[2], contexts[0]]


def test_rerank_by_overlap_preserves_members_and_input_order_for_ties():
    contexts = ["alpha one", "alpha two", "unrelated"]

    reranked = rerank_by_overlap(contexts, "alpha")

    assert reranked == contexts
    assert contexts == ["alpha one", "alpha two", "unrelated"]


def test_rerank_by_overlap_keeps_empty_query_order_unchanged():
    contexts = ["first chunk", "second chunk"]

    assert rerank_by_overlap(contexts, "") == contexts
