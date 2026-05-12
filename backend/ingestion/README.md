# Ingestion Package

## Overview

The ingestion package provides unified orchestration for lead collection from multiple sources (Reddit, HN, Twitter, RSS, GitHub, ProductHunt, StackOverflow). It handles:

- **Collection**: Coordinate all collectors to fetch data
- **Deduplication**: Prevent duplicate leads using content hashing
- **Publishing**: Send collected leads to Redis streams for processing
- **Metrics**: Track and report ingestion pipeline metrics

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Collectors │────▶│  Deduper    │────▶│  Redis      │
└─────────────┘     └─────────────┘     └─────────────┘
     │                                      │
     │                                      ▼
     │                              ┌─────────────┐
     │                              │  Stream:    │
     │                              │  lead:collected│
     │                              └─────────────┘
     │                                      │
     │                                      ▼
     │                              ┌─────────────┐
     │                              │  Analyzer   │
     │                              └─────────────┘
     │                                      │
     │                                      ▼
     │                              ┌─────────────┐
     │                              │  Scorer     │
     │                              └─────────────┘
     │                                      │
     │                                      ▼
     │                              ┌─────────────┐
     │                              │  Persist    │
     │                              └─────────────┘
     │                                      │
     ▼                                      ▼
┌─────────────┐                     ┌─────────────┐
│  Database   │                     │  Leads    │
└─────────────┘                     └─────────────┘
```

## Usage

### Programmatic Usage

```python
from backend.ingestion.orchestrator import IngestionOrchestrator

async def run_ingestion():
    orchestrator = IngestionOrchestrator()
    result = await orchestrator.run_all()
    print(f"Published: {result['published']}")
    print(f"Skipped: {result['skipped']}")
```

### CLI Usage

```bash
# Run full ingestion (all sources)
python -m backend.ingestion.cli run

# Run for specific source
python -m backend.ingestion.cli run --source reddit

# Preview which collectors would be used
python -m backend.ingestion.cli preview --mode b2b_sales

# List all available sources
python -m backend.ingestion.cli list-sources

# Test a single collector
python -m backend.ingestion.cli test --source github
```

### Celery Integration

The ingestion package integrates with the Celery pipeline:

```python
# In workers/pipeline.py
from backend.ingestion.orchestrator import IngestionOrchestrator

@celery_app.task
def collect_and_publish():
    orchestrator = IngestionOrchestrator()
    return asyncio.run(orchestrator.run_all())
```

## Configuration

The ingestion orchestrator reads profile settings from the database to enable adaptive collection:

- **Mode**: Determines collection behavior (e.g., "b2b_sales", "hiring")
- **Include Keywords**: Sources to prioritize
- **Exclude Keywords**: Sources to filter out

## Metrics

The package tracks:

- `published`: Leads successfully published to stream
- `skipped`: Duplicates or filtered posts
- `failed`: Collection errors
- `duration_seconds`: Total ingestion time
- `success_rate`: Percentage of published vs total

## Extending

### Adding a New Source

1. Create a collector in `backend/collectors/`
2. Register it in `backend/ingestion/collectors.py`:
   ```python
   def get_collectors():
       return [
           # ... existing collectors
           MyNewCollector(),
       ]
   ```
3. Add source name to `get_source_names()`
4. Register in `get_collector_by_source()` mapping

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Package exports |
| `collectors.py` | Collector factory and configuration |
| `orchestrator.py` | Main orchestration logic |
| `metrics.py` | Metrics tracking and reporting |
| `cli.py` | CLI commands for manual runs |
