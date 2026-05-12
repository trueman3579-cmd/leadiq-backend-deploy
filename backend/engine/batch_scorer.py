"""
backend/engine/batch_scorer.py — Batch scoring engine for parallel lead evaluation.
Processes 100+ leads in parallel using asyncio + optional subprocess LLM workers.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from backend.engine.scorer import MultiDimensionalScorer
from backend.llm.fallback_chain import FallbackChain

logger = logging.getLogger(__name__)


class BatchScorer:
    """Parallel scoring for large lead batches."""

    def __init__(self, use_llm: bool = True, max_concurrency: int = 20) -> None:
        self.scorer = MultiDimensionalScorer()
        self.llm = FallbackChain() if use_llm else None
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def score_batch(self, posts: list[Any]) -> list[dict]:
        """Score all posts in parallel with rate limiting."""
        tasks = [self._score_one(post) for post in posts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Batch score failed for post %d: %s", i, result)
                continue
            scored.append(result)

        logger.info("Batch scored %d/%d posts", len(scored), len(posts))
        return scored

    async def _score_one(self, post: Any) -> dict:
        async with self._semaphore:
            text = f"{post.title}\n{post.body}"
            score = self.scorer.score(text, sources=[post.source], recency_days=0)

            # LLM boost (4-tier fallback)
            if self.llm and score.overall >= 40:
                try:
                    llm_scores = await self.llm.classify(text)
                    if llm_scores:
                        for dim, dim_score in llm_scores.items():
                            if dim in score.dimensions:
                                score.dimensions[dim] = max(score.dimensions[dim], dim_score)

                        # Recalculate using sqrt scaling
                        weighted = sum(
                            v * self.scorer.DIM_WEIGHTS.get(k, 0)
                            for k, v in score.dimensions.items()
                        )
                        score.overall = min(int(math.sqrt(max(weighted, 1)) * 2.5), 100)
                        score.confidence = score.classify()
                except Exception as e:
                    logger.debug("LLM batch boost failed: %s", e)

            return {"post": post, "score": score}


async def score_leads_parallel(posts: list[Any], concurrency: int = 20) -> list[dict]:
    """Convenience function for parallel batch scoring."""
    batch = BatchScorer(max_concurrency=concurrency)
    return await batch.score_batch(posts)