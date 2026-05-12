"""
backend/services/batch_processor.py -- Async Batch Processor for High-Volume Lead Ingestion

Provides configurable batch processing with controlled concurrency, per-item error
handling, retry support, and structured logging. Designed to process 1000+ leads/minute.

Usage:
    from backend.services.batch_processor import BatchProcessor, BatchConfig

    config = BatchConfig(batch_size=50, max_concurrent=5)
    processor = BatchProcessor(config)

    results = await processor.process_batch(leads, my_processor_func)
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class BatchConfig:
    """Configuration for the batch processor.

    Attributes:
        batch_size: Number of leads per chunk. Default 100.
        max_concurrent: Maximum number of chunks processed in parallel. Default 10.
        timeout_seconds: Timeout per chunk in seconds. Default 30.
        retry_attempts: Number of retry attempts for failed items. Default 3.
        retry_delay_seconds: Delay between retries in seconds. Default 1.
    """
    batch_size: int = 100
    max_concurrent: int = 10
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0


class BatchProcessor:
    """Process leads in batches with controlled concurrency and error handling.

    Splits a list of leads into chunks, processes them in parallel using an
    asyncio.Semaphore for concurrency control. Per-item failures are logged and
    collected rather than failing the entire batch.
    """

    def __init__(self, config: BatchConfig | None = None) -> None:
        """Initialise the batch processor.

        Args:
            config: Batch configuration. Uses defaults if None.
        """
        self.config: BatchConfig = config or BatchConfig()
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(self.config.max_concurrent)

    async def process_batch(
        self,
        leads: list[dict[str, Any]],
        processor: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> list[dict[str, Any]]:
        """Process a batch of leads with controlled concurrency.

        Splits leads into chunks based on batch_size and processes all chunks
        in parallel. Per-chunk timeouts and per-item errors are handled gracefully.

        Args:
            leads: List of lead dictionaries to process.
            processor: Async callable that processes a single lead and returns a dict.

        Returns:
            Flattened list of processed lead dictionaries. Failed items are excluded
            and logged as warnings.
        """
        if not leads:
            logger.debug("batch_processor_empty_batch")
            return []

        chunks = [
            leads[i : i + self.config.batch_size]
            for i in range(0, len(leads), self.config.batch_size)
        ]

        logger.info(
            "batch_processor_start",
            total_leads=len(leads),
            chunk_count=len(chunks),
            batch_size=self.config.batch_size,
            max_concurrent=self.config.max_concurrent,
        )

        tasks = [self._process_chunk(chunk, processor) for chunk in chunks]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed: list[dict[str, Any]] = []
        for chunk_idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "batch_chunk_failed",
                    chunk_index=chunk_idx,
                    error=str(result),
                    error_type=type(result).__name__,
                )
            elif isinstance(result, list):
                processed.extend(result)

        logger.info(
            "batch_processor_complete",
            processed=len(processed),
            total=len(leads),
            failed=len(leads) - len(processed),
        )

        return processed

    async def _process_chunk(
        self,
        chunk: list[dict[str, Any]],
        processor: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> list[dict[str, Any]]:
        """Process a single chunk of leads with semaphore control and timeout.

        Each lead is processed individually. Failed items are caught and logged
        so a single failure does not abort the entire chunk.

        Args:
            chunk: List of lead dictionaries for this chunk.
            processor: Async callable that processes a single lead.

        Returns:
            List of successfully processed lead dictionaries for this chunk.
        """
        async with self.semaphore:
            results: list[dict[str, Any]] = []
            for lead in chunk:
                try:
                    result = await asyncio.wait_for(
                        self._process_with_retry(lead, processor),
                        timeout=self.config.timeout_seconds,
                    )
                    if result is not None:
                        results.append(result)
                except asyncio.TimeoutError:
                    logger.warning(
                        "lead_processing_timeout",
                        lead_id=lead.get("id", lead.get("external_id", "unknown")),
                        timeout=self.config.timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(
                        "lead_processing_failed",
                        lead_id=lead.get("id", lead.get("external_id", "unknown")),
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
            return results

    async def _process_with_retry(
        self,
        lead: dict[str, Any],
        processor: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> Any:
        """Process a single lead with retry logic.

        Retries up to config.retry_attempts times with a configurable delay
        between attempts.

        Args:
            lead: Lead dictionary to process.
            processor: Async callable that processes a single lead.

        Returns:
            Processed result from the processor.

        Raises:
            Exception: The last exception if all retry attempts fail.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                return await processor(lead)
            except Exception as exc:
                last_exception = exc
                if attempt < self.config.retry_attempts:
                    logger.debug(
                        "lead_processing_retry",
                        lead_id=lead.get("id", lead.get("external_id", "unknown")),
                        attempt=attempt,
                        max_retries=self.config.retry_attempts,
                        error=str(exc),
                    )
                    await asyncio.sleep(self.config.retry_delay_seconds)

        logger.warning(
            "lead_processing_retries_exhausted",
            lead_id=lead.get("id", lead.get("external_id", "unknown")),
            attempts=self.config.retry_attempts,
            error=str(last_exception),
        )
        if last_exception is not None:
            raise last_exception
        return None
