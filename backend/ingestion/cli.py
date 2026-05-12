"""
ingestion/cli.py — CLI commands for ingestion operations.

Provides command-line interface for manual ingestion runs.
"""
from __future__ import annotations

import asyncio
import click

from backend.ingestion.orchestrator import IngestionOrchestrator
from backend.ingestion.collectors import get_collectors, get_source_names


@click.group()
def ingestion():
    """Ingestion commands for LeadIQ lead collection."""
    pass


@ingestion.command()
@click.option("--source", "-s", default=None, help="Specific source to collect (e.g., reddit, hn)")
@click.option("--mode", "-m", default="b2b_sales", help="Profile mode for adaptive collection")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def run(source: str | None, mode: str, verbose: bool) -> None:
    """
    Run lead ingestion.

    Collects from all sources (or a specific source if --source is provided),
    deduplicates, and publishes to Redis stream.
    """
    orchestrator = IngestionOrchestrator()

    if source:
        click.echo(f"Running ingestion for source: {source}")
        result = asyncio.run(orchestrator.run_single_source(source))
    else:
        click.echo("Running full ingestion (all sources)")
        result = asyncio.run(orchestrator.run_all())

    # Display results
    click.echo("\n" + "=" * 50)
    click.echo("INGESTION RESULTS")
    click.echo("=" * 50)
    click.echo(f"Mode: {result.get('mode', mode)}")
    click.echo(f"Published: {result['published']}")
    click.echo(f"Skipped (duplicates): {result['skipped']}")
    click.echo(f"Failed: {result.get('failed', 0)}")

    if verbose:
        click.echo(f"Total collected: {result['published'] + result['skipped']}")

    click.echo("=" * 50)


@ingestion.command(name="list-sources")
def list_sources() -> None:
    """List all available data sources."""
    sources = get_source_names()
    click.echo("Available sources:")
    for source in sources:
        click.echo(f"  - {source}")


@ingestion.command()
@click.option("--mode", "-m", default="b2b_sales", help="Profile mode for adaptive collection")
def preview(mode: str) -> None:
    """
    Preview which sources would be collected.

    Shows the collector configuration without actually running collection.
    """

    click.echo(f"Previewing collection for mode: {mode}")
    click.echo("\nCollectors that would be used:")

    collectors = get_collectors(mode=mode)
    for collector in collectors:
        click.echo(f"  - {collector.source}")


@ingestion.command()
@click.option("--source", "-s", required=True, help="Source to test")
def test(source: str) -> None:
    """
    Test a single collector without deduplication or publishing.

    Useful for debugging individual collectors.
    """
    from backend.ingestion.collectors import get_collector_by_source

    click.echo(f"Testing collector: {source}")

    try:
        collector_class = get_collector_by_source(source)
        collector = collector_class()

        # Run collection
        posts = asyncio.run(collector.collect())

        click.echo(f"Collected {len(posts)} posts from {source}")
        if posts:
            click.echo("\nFirst 3 posts:")
            for i, post in enumerate(posts[:3]):
                click.echo(f"  {i+1}. {post.title or post.url}")
    except Exception as exc:
        click.echo(f"Error: {exc}")
        raise click.Abort() from exc


if __name__ == "__main__":
    ingestion()
