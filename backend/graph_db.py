"""
backend/graph_db.py — Neo4j graph database layer for relationship intelligence.
Tracks: orgs, people, posts, tech, and relationships between them.
All queries are Cypher. Zero-cost (Neo4j Community Edition is free).
"""
from __future__ import annotations

import logging

from backend.shared.config import settings

logger = logging.getLogger(__name__)

NEO4J_URI = settings.NEO4J_URI
NEO4J_USER = settings.NEO4J_USER
NEO4J_PASS = settings.NEO4J_PASS


class GraphDB:
    """Neo4j graph database for lead relationship intelligence."""

    def __init__(self) -> None:
        self._driver = None

    async def connect(self) -> None:
        from neo4j import AsyncGraphDatabase
        self._driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        await self._driver.verify_connectivity()
        logger.info("GraphDB connected to %s", NEO4J_URI)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    async def add_entity(self, label: str, id_field: str, entity_id: str, **properties) -> dict:
        """Upsert an entity node with properties."""
        assert self._driver is not None
        async with self._driver.session() as session:
            cypher = f"""
                MERGE (e:{label} {{ {id_field}: $entity_id }})
                SET e += $props
                RETURN e
            """
            result = await session.run(cypher, {"entity_id": entity_id, "props": properties})
            record = await result.single()
            return dict(record["e"]) if record else {}

    async def relate(self, label_a: str, id_a: str, relationship: str, label_b: str, id_b: str) -> None:
        """Create a relationship between two entities."""
        assert self._driver is not None
        async with self._driver.session() as session:
            cypher = f"""MATCH (a:{label_a}), (b:{label_b})
WHERE a.id = $id_a AND b.id = $id_b
MERGE (a)-[r:{relationship}]->(b)
RETURN r"""
            await session.run(cypher, {"id_a": id_a, "id_b": id_b})

    async def get_org_leads(self, org_name: str) -> list[dict]:
        """Find all leads associated with an organization."""
        assert self._driver is not None
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (o:Organization {name: $org_name})<-[:WORKS_AT]-(p:Person)-[:AUTHORED]->(post:Post) RETURN post.title AS title, post.url AS url, p.name AS author ORDER BY post.score DESC",
                org_name,
            )
            return [dict(r) for r in await result.data()]

    async def create_indexes(self) -> None:
        """Create unique constraints for performance."""
        assert self._driver is not None
        async with self._driver.session() as session:
            try:
                await session.run("CREATE CONSTRAINT org_name IF NOT EXISTS FOR (o:Organization) REQUIRE o.name IS UNIQUE")
                await session.run("CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE")
                logger.info("GraphDB unique constraints created")
            except Exception as e:
                logger.warning("GraphDB constraint creation: %s", e)
