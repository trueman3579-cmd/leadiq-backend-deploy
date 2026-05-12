"""
backend/actors — Worker actors for job platform collectors.

Each actor wraps a collector in a Celery-compatible task function that
can be called from the pipeline or scheduled via beat.
"""
