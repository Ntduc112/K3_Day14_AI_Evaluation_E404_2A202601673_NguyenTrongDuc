"""Run the optional framework-comparison and retrieval-reranking exercises.

The framework comparison uses the same five saved RAG traces, evaluator model,
answers, and retrieved contexts in RAGAS and DeepEval.  It intentionally does
not regenerate domain-assistant answers.

Official API references:
- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/
- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/answer_relevance/
- https://deepeval.com/docs/metrics-faithfulness
- https://deepeval.com/docs/metrics-answer-relevancy
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv

from evaluate_answers import load_evaluation_inputs
from template import RAGASEvaluator, rerank_by_overlap


COMPARISON_IDS = ("E01", "M03", "H05", "A01", "A02")
EVALUATOR_MODEL = "gpt-4.1-mini"
EMBEDDING_MODEL = "text-embedding-3-small"
PASS_THRESHOLD = 0.5


def _score_ragas(pair: Any, answer: str, llm: Any, embeddings: Any) -> dict[str, float]:
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness

    faithfulness = Faithfulness(llm=llm).score(
        user_input=pair.question,
        response=answer,
        retrieved_contexts=pair.retrieved_contexts,
    ).value
    relevance = AnswerRelevancy(llm=llm, embeddings=embeddings).score(
        user_input=pair.question,
        response=answer,
    ).value
    return {
        "faithfulness": float(faithfulness),
        "answer_relevance": float(relevance),
    }


def _score_deepeval(pair: Any, answer: str) -> dict[str, float]:
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input=pair.question,
        actual_output=answer,
        expected_output=pair.expected_answer,
        retrieval_context=pair.retrieved_contexts,
    )
    faithfulness = FaithfulnessMetric(
        threshold=PASS_THRESHOLD,
        model=EVALUATOR_MODEL,
        include_reason=False,
        async_mode=False,
    )
    relevance = AnswerRelevancyMetric(
        threshold=PASS_THRESHOLD,
        model=EVALUATOR_MODEL,
        include_reason=False,
        async_mode=False,
    )
    faithfulness.measure(test_case)
    relevance.measure(test_case)
    return {
        "faithfulness": float(faithfulness.score),
        "answer_relevance": float(relevance.score),
    }


def _run_framework_comparison(pairs: list[Any], answers: dict[str, str]) -> dict[str, Any]:
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    client = AsyncOpenAI()
    ragas_llm = llm_factory(EVALUATOR_MODEL, client=client)
    ragas_embeddings = embedding_factory(
        "openai",
        model=EMBEDDING_MODEL,
        client=client,
    )
    selected = {pair.metadata["id"]: pair for pair in pairs}
    rows: list[dict[str, Any]] = []
    for case_id in COMPARISON_IDS:
        pair = selected[case_id]
        answer = answers[pair.question]
        print(f"Scoring {case_id} with RAGAS...", flush=True)
        ragas_scores = _score_ragas(pair, answer, ragas_llm, ragas_embeddings)
        print(f"Scoring {case_id} with DeepEval...", flush=True)
        deepeval_scores = _score_deepeval(pair, answer)
        rows.append(
            {
                "id": case_id,
                "ragas": ragas_scores,
                "deepeval": deepeval_scores,
                "ragas_passed": all(
                    value >= PASS_THRESHOLD for value in ragas_scores.values()
                ),
                "deepeval_passed": all(
                    value >= PASS_THRESHOLD for value in deepeval_scores.values()
                ),
            }
        )

    return {
        "case_ids": list(COMPARISON_IDS),
        "evaluator_model": EVALUATOR_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "pass_threshold": PASS_THRESHOLD,
        "framework_versions": {
            "ragas": version("ragas"),
            "deepeval": version("deepeval"),
            "langchain-community": version("langchain-community"),
        },
        "results": rows,
        "averages": {
            framework: {
                metric: mean(row[framework][metric] for row in rows)
                for metric in ("faithfulness", "answer_relevance")
            }
            for framework in ("ragas", "deepeval")
        },
        "failed_ids": {
            "ragas": [row["id"] for row in rows if not row["ragas_passed"]],
            "deepeval": [row["id"] for row in rows if not row["deepeval_passed"]],
        },
    }


def _run_reranking(pairs: list[Any]) -> dict[str, Any]:
    evaluator = RAGASEvaluator()
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        before = pair.retrieved_contexts
        after = rerank_by_overlap(before, pair.question)
        recall_before = evaluator.evaluate_context_recall(
            before, pair.expected_answer
        )
        recall_after = evaluator.evaluate_context_recall(
            after, pair.expected_answer
        )
        precision_before = evaluator.evaluate_context_precision(
            before, pair.expected_answer
        )
        precision_after = evaluator.evaluate_context_precision(
            after, pair.expected_answer
        )
        rows.append(
            {
                "id": pair.metadata["id"],
                "recall_before": recall_before,
                "recall_after": recall_after,
                "precision_before": precision_before,
                "precision_after": precision_after,
                "delta_precision": precision_after - precision_before,
                "order_changed": before != after,
                "retrieved_count": len(before),
                "same_chunk_multiset": sorted(before) == sorted(after),
            }
        )
    return {
        "results": rows,
        "averages": {
            field: mean(row[field] for row in rows)
            for field in (
                "recall_before",
                "recall_after",
                "precision_before",
                "precision_after",
                "delta_precision",
            )
        },
    }


def main() -> int:
    load_dotenv(dotenv_path=".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for Exercise 3.4")

    pairs, answers = load_evaluation_inputs(
        "golden_dataset.json", "artifacts/actual_answers.json"
    )
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "framework_comparison": _run_framework_comparison(pairs, answers),
        "reranking": _run_reranking(pairs),
    }
    output = Path("artifacts/bonus_results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
