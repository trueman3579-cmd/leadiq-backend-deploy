"""
backend/services/connection_pool.py -- Connection Pool Manager for Database and HTTP

Manages lifecycle of asyncpg database pools and httpx.AsyncClient instances for
the entire application. Ensures connections are reused, limits are respected, and
all resources are cleaned up gracefully on shutdown.

Usage:
    from backend.services.connection_pool import ConnectionPoolManager

    pool_manager = ConnectionPoolManager()

    # Database pool
    db_pool = await pool_manager.get_db_pool("default", "postgresql://...")

    # HTTP client
    http = pool_manager.get_http_client("github")

    # At shutdown:
    await pool_manager.close_all()
"""
from __future__ import annotations

from typing import Any

import asyncpg
import httpx
import structlog

logger = structlog.get_logger()


class ConnectionPoolManager:
    """Manage connection pools for PostgreSQL databases and HTTP clients.

    Provides lazy initialisation, reuse, health checking, and graceful shutdown
    for all pooled resources.
    """

    def __init__(self) -> None:
        """Initialise an empty pool manager."""
        self.db_pools: dict[str, asyncpg.Pool] = {}
        self.http_clients: dict[str, httpx.AsyncClient] = {}

    # ── Database Pools ──────────────────────────────────────────────────────────────

    async def create_db_pool(
        self,
        name: str,
        dsn: str,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: int = 60,
    ) -> asyncpg.Pool:
        """Create a new PostgreSQL connection pool.

        If a pool with the given name already exists, the existing pool is
        returned and a new one is not created.

        Args:
            name: Unique identifier for this pool.
            dsn: PostgreSQL DSN connection string.
            min_size: Minimum number of connections to keep in the pool.
            max_size: Maximum number of connections in the pool.
            command_timeout: Timeout in seconds for database commands.

        Returns:
            The created or existing asyncpg.Pool instance.
        """
        if name in self.db_pools:
            logger.debug("db_pool_already_exists", name=name)
            return self.db_pools[name]

        logger.info(
            "db_pool_creating",
            name=name,
            min_size=min_size,
            max_size=max_size,
        )

        try:
            pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=min_size,
                max_size=max_size,
                command_timeout=command_timeout,
                server_settings={
                    "jit": "off",
                    "application_name": "leadiq",
                },
            )
            self.db_pools[name] = pool
            logger.info("db_pool_created", name=name)
            return pool
        except Exception as exc:
            logger.error(
                "db_pool_creation_failed",
                name=name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

    async def get_db_pool(self, name: str) -> asyncpg.Pool:
        """Retrieve an existing database pool by name.

        Args:
            name: The pool identifier.

        Returns:
            The asyncpg.Pool instance.

        Raises:
            KeyError: If no pool with the given name exists.
        """
        if name not in self.db_pools:
            raise KeyError(f"Database pool '{name}' not found. Call create_db_pool first.")
        return self.db_pools[name]

    async def close_db_pool(self, name: str) -> None:
        """Close a specific database pool and remove it from the manager.

        Args:
            name: The pool identifier to close.
        """
        pool = self.db_pools.pop(name, None)
        if pool is not None:
            try:
                await pool.close()
                logger.info("db_pool_closed", name=name)
            except Exception as exc:
                logger.error(
                    "db_pool_close_failed",
                    name=name,
                    error=str(exc),
                )

    # ── HTTP Clients ────────────────────────────────────────────────────────────────

    def create_http_client(
        self,
        name: str,
        limits: httpx.Limits | None = None,
        timeout_config: httpx.Timeout | None = None,
        **kwargs: Any,
    ) -> httpx.AsyncClient:
        """Create a new HTTP client with connection pooling.

        If a client with the given name already exists, the existing client is
        returned and a new one is not created.

        Args:
            name: Unique identifier for this client.
            limits: httpx.Limits for connection pooling. Defaults to 20 keepalive
                    connections and 100 max connections.
            timeout_config: httpx.Timeout configuration. Defaults to 30s overall
                            with 5s connect timeout.
            **kwargs: Additional keyword arguments forwarded to httpx.AsyncClient.

        Returns:
            The created or existing httpx.AsyncClient instance.
        """
        if name in self.http_clients:
            logger.debug("http_client_already_exists", name=name)
            return self.http_clients[name]

        resolved_limits = limits or httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
        )
        resolved_timeout = timeout_config or httpx.Timeout(30.0, connect=5.0)

        client = httpx.AsyncClient(
            limits=resolved_limits,
            timeout=resolved_timeout,
            http2=True,
            **kwargs,
        )
        self.http_clients[name] = client
        logger.info("http_client_created", name=name, http2=True)
        return client

    def get_http_client(self, name: str) -> httpx.AsyncClient:
        """Retrieve an existing HTTP client by name.

        Args:
            name: The client identifier.

        Returns:
            The httpx.AsyncClient instance.

        Raises:
            KeyError: If no client with the given name exists.
        """
        if name not in self.http_clients:
            raise KeyError(f"HTTP client '{name}' not found. Call create_http_client first.")
        return self.http_clients[name]

    async def close_http_client(self, name: str) -> None:
        """Close a specific HTTP client and remove it from the manager.

        Args:
            name: The client identifier to close.
        """
        client = self.http_clients.pop(name, None)
        if client is not None:
            try:
                await client.aclose()
                logger.info("http_client_closed", name=name)
            except Exception as exc:
                logger.error(
                    "http_client_close_failed",
                    name=name,
                    error=str(exc),
                )

    # ── Lifecycle ───────────────────────────────────────────────────────────────────

    async def close_all(self) -> None:
        """Gracefully close all database pools and HTTP clients.

        This should be called during application shutdown (e.g., FastAPI lifespan).
        Errors during close are logged but do not prevent other resources from
        closing.
        """
        logger.info(
            "connection_pool_manager_shutdown",
            db_pools=len(self.db_pools),
            http_clients=len(self.http_clients),
        )

        # Close all database pools
        pool_names = list(self.db_pools.keys())
        for name in pool_names:
            await self.close_db_pool(name)

        # Close all HTTP clients
        client_names = list(self.http_clients.keys())
        for name in client_names:
            await self.close_http_client(name)

        logger.info("connection_pool_manager_shutdown_complete")

    async def health_check(self) -> dict[str, Any]:
        """Perform a health check on all managed pools and clients.

        Returns a dictionary with the status of each pool and client.

        Returns:
            Dict with keys 'db_pools' and 'http_clients', each containing status info.
        """
        db_pool_status: dict[str, str] = {}
        for name, pool in self.db_pools.items():
            try:
                async with pool.acquire() as conn:
                    result = await conn.fetchval("SELECT 1")
                    db_pool_status[name] = "healthy" if result == 1 else "degraded"
            except Exception as exc:
                db_pool_status[name] = f"unhealthy: {exc}"

        http_client_status: dict[str, str] = {}
        for name in self.http_clients:
            http_client_status[name] = "registered"

        return {
            "db_pools": db_pool_status,
            "http_clients": http_client_status,
            "total_db_pools": len(self.db_pools),
            "total_http_clients": len(self.http_clients),
        }
