"""
Reranker Bakeoff Framework
Comparative evaluation of reranker models on UK immigration corpus.

Evaluates:
- DeepInfra Qwen/Qwen3-Reranker-8B
- Cohere rerank-english-v3.0
- Baseline (RRF without reranking)

Metrics:
- NDCG@10 (Normalized Discounted Cumulative Gain)
- MRR (Mean Reciprocal Rank)
- Score distribution (variance, range)
- Latency (P95)
- Cost per 1M reranks
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import numpy as np
from scipy.stats import spearmanr
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rag.components.deepinfra_reranker import DeepInfraReranker
from rag.components.cohere_reranker import CohereReranker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class QueryTestCase:
    """Single test case for bakeoff."""
    query_id: str
    query_text: str
    documents: List[str]
    relevance_scores: List[int]  # 0-3 scale (0=irrelevant, 3=highly relevant)
    category: str  # "factual", "procedural", "multi-hop"


@dataclass
class ModelResult:
    """Results for a single model."""
    model_name: str
    ndcg_at_10: float
    mrr: float
    score_variance_mean: float
    score_variance_std: float
    score_range_mean: Tuple[float, float]
    latency_p50: float
    latency_p95: float
    latency_p99: float
    cost_per_1m: float
    rrf_correlation_mean: float  # Spearman correlation with RRF scores
    queries_tested: int


class RerankerBakeoff:
    """
    Reranker model comparison framework.

    Usage:
        bakeoff = RerankerBakeoff()
        test_cases = bakeoff.load_test_cases("test_queries.json")
        results = bakeoff.run_comparison(test_cases)
        bakeoff.print_report(results)
    """

    def __init__(self):
        """Initialize bakeoff framework."""
        self.models = {}
        self._init_models()

    def _init_models(self):
        """Initialize reranker models if API keys available."""
        # DeepInfra Qwen
        if os.getenv("DEEPINFRA_API_KEY"):
            try:
                self.models["qwen-8b"] = DeepInfraReranker(
                    model="Qwen/Qwen3-Reranker-8B"
                )
                logger.info("✓ Initialized DeepInfra Qwen-8B")
            except Exception as e:
                logger.warning(f"Failed to initialize Qwen-8B: {e}")

        # Cohere
        if os.getenv("COHERE_API_KEY"):
            try:
                self.models["cohere-v3"] = CohereReranker(
                    model="rerank-english-v3.0"
                )
                logger.info("✓ Initialized Cohere rerank-english-v3.0")
            except Exception as e:
                logger.warning(f"Failed to initialize Cohere: {e}")

        if not self.models:
            logger.error(
                "No reranker models initialized. "
                "Set DEEPINFRA_API_KEY and/or COHERE_API_KEY environment variables."
            )

    def load_test_cases(self, filepath: str) -> List[QueryTestCase]:
        """
        Load test cases from JSON file.

        Format:
        [
            {
                "query_id": "q001",
                "query_text": "What is BNO visa?",
                "documents": ["doc1 text", "doc2 text", ...],
                "relevance_scores": [3, 2, 0, 1, ...],
                "category": "factual"
            },
            ...
        ]

        Args:
            filepath: Path to test cases JSON file

        Returns:
            List of QueryTestCase objects
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        test_cases = []
        for item in data:
            test_cases.append(QueryTestCase(**item))

        logger.info(f"Loaded {len(test_cases)} test cases from {filepath}")
        return test_cases

    def compute_ndcg(
        self,
        relevance_scores: List[int],
        reranked_indices: List[int],
        k: int = 10
    ) -> float:
        """
        Compute NDCG@K.

        Args:
            relevance_scores: Ground truth relevance (0-3 scale)
            reranked_indices: Document indices after reranking (sorted by score)
            k: Number of top results to consider

        Returns:
            NDCG@K score (0-1)
        """
        # DCG@K
        dcg = 0.0
        for i, idx in enumerate(reranked_indices[:k]):
            relevance = relevance_scores[idx]
            discount = np.log2(i + 2)  # i+2 because positions are 0-indexed
            dcg += relevance / discount

        # Ideal DCG@K (sort by relevance)
        ideal_indices = sorted(
            range(len(relevance_scores)),
            key=lambda i: relevance_scores[i],
            reverse=True
        )
        idcg = 0.0
        for i, idx in enumerate(ideal_indices[:k]):
            relevance = relevance_scores[idx]
            discount = np.log2(i + 2)
            idcg += relevance / discount

        # NDCG
        if idcg == 0:
            return 0.0
        return dcg / idcg

    def compute_mrr(
        self,
        relevance_scores: List[int],
        reranked_indices: List[int]
    ) -> float:
        """
        Compute Mean Reciprocal Rank.

        Args:
            relevance_scores: Ground truth relevance (0-3 scale)
            reranked_indices: Document indices after reranking

        Returns:
            MRR score
        """
        # Find first relevant document (relevance >= 2)
        for rank, idx in enumerate(reranked_indices, start=1):
            if relevance_scores[idx] >= 2:
                return 1.0 / rank

        return 0.0  # No relevant document found

    def evaluate_model(
        self,
        model_name: str,
        model,
        test_cases: List[QueryTestCase],
        rrf_scores: Optional[Dict[str, List[float]]] = None
    ) -> ModelResult:
        """
        Evaluate single model on test cases.

        Args:
            model_name: Model identifier
            model: Reranker instance
            test_cases: List of test queries
            rrf_scores: Optional RRF baseline scores for correlation

        Returns:
            ModelResult with aggregated metrics
        """
        ndcg_scores = []
        mrr_scores = []
        variances = []
        ranges = []
        latencies = []
        rrf_correlations = []

        logger.info(f"Evaluating {model_name} on {len(test_cases)} queries...")

        for test_case in test_cases:
            try:
                # Rerank documents
                result = model.rerank(
                    query=test_case.query_text,
                    documents=test_case.documents
                )

                # Sort documents by reranked scores
                reranked_indices = sorted(
                    range(len(result.scores)),
                    key=lambda i: result.scores[i],
                    reverse=True
                )

                # Compute NDCG@10
                ndcg = self.compute_ndcg(
                    test_case.relevance_scores,
                    reranked_indices,
                    k=10
                )
                ndcg_scores.append(ndcg)

                # Compute MRR
                mrr = self.compute_mrr(
                    test_case.relevance_scores,
                    reranked_indices
                )
                mrr_scores.append(mrr)

                # Track score distribution
                variances.append(result.score_variance)
                ranges.append(result.score_range)
                latencies.append(result.latency_ms)

                # RRF correlation (if baseline provided)
                if rrf_scores and test_case.query_id in rrf_scores:
                    correlation, _ = spearmanr(
                        result.scores,
                        rrf_scores[test_case.query_id]
                    )
                    rrf_correlations.append(correlation)

            except Exception as e:
                logger.error(
                    f"Failed to evaluate query {test_case.query_id}: {e}"
                )
                continue

        # Aggregate results
        return ModelResult(
            model_name=model_name,
            ndcg_at_10=float(np.mean(ndcg_scores)),
            mrr=float(np.mean(mrr_scores)),
            score_variance_mean=float(np.mean(variances)),
            score_variance_std=float(np.std(variances)),
            score_range_mean=(
                float(np.mean([r[0] for r in ranges])),
                float(np.mean([r[1] for r in ranges]))
            ),
            latency_p50=float(np.percentile(latencies, 50)),
            latency_p95=float(np.percentile(latencies, 95)),
            latency_p99=float(np.percentile(latencies, 99)),
            cost_per_1m=self._estimate_cost(model_name),
            rrf_correlation_mean=float(np.mean(rrf_correlations)) if rrf_correlations else 0.0,
            queries_tested=len(ndcg_scores)
        )

    def _estimate_cost(self, model_name: str) -> float:
        """Estimate cost per 1M reranks."""
        cost_map = {
            "qwen-8b": 50.0,  # DeepInfra estimate
            "cohere-v3": 200.0,  # Cohere published pricing
            "baseline": 0.0  # RRF only
        }
        return cost_map.get(model_name, 0.0)

    def run_comparison(
        self,
        test_cases: List[QueryTestCase],
        include_baseline: bool = True
    ) -> Dict[str, ModelResult]:
        """
        Run bakeoff comparison across all models.

        Args:
            test_cases: Test query dataset
            include_baseline: Include RRF-only baseline

        Returns:
            Dict mapping model name to results
        """
        results = {}

        # Evaluate each model
        for model_name, model in self.models.items():
            try:
                result = self.evaluate_model(model_name, model, test_cases)
                results[model_name] = result
                logger.info(
                    f"✓ {model_name}: NDCG@10={result.ndcg_at_10:.3f}, "
                    f"MRR={result.mrr:.3f}, P95={result.latency_p95:.0f}ms"
                )
            except Exception as e:
                logger.error(f"Failed to evaluate {model_name}: {e}")

        return results

    def print_report(self, results: Dict[str, ModelResult]):
        """
        Print comparison report to console.

        Args:
            results: Model results from run_comparison
        """
        print("\n" + "=" * 80)
        print("RERANKER BAKEOFF RESULTS")
        print("=" * 80)

        # Sort by NDCG@10 (descending)
        sorted_models = sorted(
            results.items(),
            key=lambda x: x[1].ndcg_at_10,
            reverse=True
        )

        print("\n📊 RANKING QUALITY")
        print("-" * 80)
        print(f"{'Model':<20} {'NDCG@10':<12} {'MRR':<12} {'Queries':<10}")
        print("-" * 80)
        for model_name, result in sorted_models:
            print(
                f"{model_name:<20} "
                f"{result.ndcg_at_10:<12.3f} "
                f"{result.mrr:<12.3f} "
                f"{result.queries_tested:<10}"
            )

        print("\n📈 SCORE DISTRIBUTION")
        print("-" * 80)
        print(f"{'Model':<20} {'Variance Mean':<15} {'Variance Std':<15} {'Range':<20}")
        print("-" * 80)
        for model_name, result in sorted_models:
            range_str = f"({result.score_range_mean[0]:.3f}, {result.score_range_mean[1]:.3f})"
            print(
                f"{model_name:<20} "
                f"{result.score_variance_mean:<15.6f} "
                f"{result.score_variance_std:<15.6f} "
                f"{range_str:<20}"
            )

        print("\n⚡ LATENCY")
        print("-" * 80)
        print(f"{'Model':<20} {'P50 (ms)':<12} {'P95 (ms)':<12} {'P99 (ms)':<12}")
        print("-" * 80)
        for model_name, result in sorted_models:
            print(
                f"{model_name:<20} "
                f"{result.latency_p50:<12.1f} "
                f"{result.latency_p95:<12.1f} "
                f"{result.latency_p99:<12.1f}"
            )

        print("\n💰 COST")
        print("-" * 80)
        print(f"{'Model':<20} {'Cost/1M reranks':<20}")
        print("-" * 80)
        for model_name, result in sorted_models:
            print(
                f"{model_name:<20} "
                f"${result.cost_per_1m:<19.2f}"
            )

        print("\n🎯 RECOMMENDATION")
        print("-" * 80)

        # Winner: Best NDCG@10
        winner = sorted_models[0]
        print(f"🏆 Best Quality: {winner[0]} (NDCG@10: {winner[1].ndcg_at_10:.3f})")

        # Value: Best quality/cost ratio
        if len(sorted_models) > 1:
            value_winner = max(
                sorted_models,
                key=lambda x: x[1].ndcg_at_10 / max(x[1].cost_per_1m, 1.0)
            )
            print(f"💎 Best Value: {value_winner[0]}")

        # Check for uniform scoring issues
        print("\n⚠️  WARNINGS")
        print("-" * 80)
        warnings_found = False
        for model_name, result in sorted_models:
            if result.score_variance_mean < 0.001:
                print(
                    f"⚠️  {model_name}: Low score variance "
                    f"({result.score_variance_mean:.6f}) - may mask RRF scores!"
                )
                warnings_found = True

        if not warnings_found:
            print("No issues detected ✓")

        print("\n" + "=" * 80)

    def save_results(self, results: Dict[str, ModelResult], filepath: str):
        """
        Save results to JSON file.

        Args:
            results: Model results from run_comparison
            filepath: Output JSON file path
        """
        output = {
            model_name: asdict(result)
            for model_name, result in results.items()
        }

        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Results saved to {filepath}")


def main():
    """Run reranker bakeoff."""
    import argparse

    parser = argparse.ArgumentParser(description="Reranker Bakeoff")
    parser.add_argument(
        "--test-cases",
        required=True,
        help="Path to test cases JSON file"
    )
    parser.add_argument(
        "--output",
        default="reranker_bakeoff_results.json",
        help="Output JSON file path"
    )

    args = parser.parse_args()

    # Run bakeoff
    bakeoff = RerankerBakeoff()
    test_cases = bakeoff.load_test_cases(args.test_cases)
    results = bakeoff.run_comparison(test_cases)

    # Print report
    bakeoff.print_report(results)

    # Save results
    bakeoff.save_results(results, args.output)


if __name__ == "__main__":
    main()
