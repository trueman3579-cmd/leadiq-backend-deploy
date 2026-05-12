# Architecture Fitness Tests

This directory contains architecture fitness tests for the Lead-iq platform.

## Overview

Architecture fitness functions verify that the system meets structural and quality criteria. These tests run as part of CI/CD to catch architectural decay early.

## Test Categories

### 1. Database Fitness
- HNSW index presence and configuration
- Composite index coverage for common query patterns
- CHECK constraint validation
- Schema drift detection

### 2. Service Architecture
- Async DB call enforcement
- Service layer separation
- Dependency injection patterns

### 3. API Contracts
- Response format compliance
- Error handling consistency
- Authentication requirements

## Running Fitness Tests

### Local Execution

```bash
cd /mnt/c/Users/USER/Downloads/b_a6LznsoAKUT-1774336963705/backend

# Run all fitness tests
pytest tests/architecture/ -v

# Run specific test suite
pytest tests/architecture/test_database.py -v

# Run with coverage
pytest tests/architecture/ --cov=backend --cov-report=term-missing -v
```

### In CI/CD

Fitness tests run automatically on every push to `main`:

```yaml
# .github/workflows/fitness.yml
name: Architecture Fitness

on:
  push:
    branches: [main]

jobs:
  fitness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Run fitness tests
        run: |
          cd backend
          pytest tests/architecture/ -v
```

### With Database Fixture

For tests that verify database state:

```bash
# Create test database
pytest tests/architecture/test_database.py \
  --db-url=postgresql://user:pass@localhost:5432/lead_iq_test \
  -v
```

## Writing New Fitness Tests

Use pytest and pytest-asyncio for async tests:

```python
# tests/architecture/test_database.py
import pytest
from sqlalchemy import text

@pytest.mark.database
async def test_hnsw_index_exists(async_engine):
    """Verify HNSW index exists on leads table."""
    async with async_engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'leads'
            AND indexname = 'leads_embedding_hnsw_idx'
        """))
        row = result.fetchone()
        assert row is not None, "HNSW index not found on leads table"
```

## Database Migration Verification

Before deploying migrations:

```bash
cd /mnt/c/Users/USER/Downloads/b_a6LznsoAKUT-1774336963705/backend

# Check migration status
alembic head
alembic current

# Run pending migrations
alembic upgrade head

# Verify fitness tests pass
pytest tests/architecture/ -v
```

## Architecture Decision Records

Related architecture decisions are documented in:

- `docs/architecture/` - High-level design docs
- `docs/migrations/` - Database migration guide
- `CHECKPOINT.md` - Implementation status
