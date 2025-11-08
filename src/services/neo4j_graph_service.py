"""
Neo4J Graph Service - Graph Statistics and Health Checks

Implements NEO4J-001 specification:
- Graph statistics (node counts, relationship counts, density)
- Health checks for graph integrity
- Entity lookup and visualization data
- Graph maintenance utilities

Used by API endpoints for monitoring and administration.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)


class Neo4JGraphService:
    """
    Service for Neo4J graph operations, health checks, and statistics.

    Provides:
    - Graph statistics (node/relationship counts)
    - Health checks (orphaned nodes, broken references)
    - Entity details and relationships
    - Visualization data export
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
    ):
        """
        Initialize Neo4J graph service.

        Args:
            neo4j_uri: Neo4J connection URI (bolt://localhost:7687)
            neo4j_user: Neo4J username
            neo4j_password: Neo4J password
            neo4j_database: Neo4J database name
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database

        # Initialize Neo4J driver
        self.driver: Optional[Driver] = None
        self._connect_neo4j()

        logger.info(f"Neo4JGraphService initialized (database: {neo4j_database})")

    def _connect_neo4j(self) -> None:
        """Establish Neo4J connection."""
        try:
            self.driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )
            # Verify connection
            self.driver.verify_connectivity()
            logger.info(f"✓ Neo4J connected: {self.neo4j_uri}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4J: {e}")
            self.driver = None
            raise RuntimeError(f"Neo4J connection failed: {e}") from e

    def close(self) -> None:
        """Close Neo4J driver connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4J driver closed")

    def get_graph_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive graph statistics.

        Returns:
            Dictionary with node counts, relationship counts, graph density, etc.
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                # Get node counts by type
                node_counts_query = """
                MATCH (n)
                RETURN labels(n) AS labels, count(n) AS count
                """
                node_result = session.run(node_counts_query)
                node_counts = {}

                for record in node_result:
                    labels = record["labels"]
                    count = record["count"]
                    # Use first label as primary type
                    if labels:
                        primary_label = labels[0] if isinstance(labels, list) else str(labels)
                        node_counts[primary_label] = count

                # Get relationship counts by type
                rel_counts_query = """
                MATCH ()-[r]->()
                RETURN type(r) AS rel_type, count(r) AS count
                """
                rel_result = session.run(rel_counts_query)
                relationship_counts = {}

                for record in rel_result:
                    rel_type = record["rel_type"]
                    count = record["count"]
                    relationship_counts[rel_type] = count

                # Get total counts
                total_nodes_query = "MATCH (n) RETURN count(n) AS total"
                total_nodes = session.run(total_nodes_query).single()["total"]

                total_rels_query = "MATCH ()-[r]->() RETURN count(r) AS total"
                total_rels = session.run(total_rels_query).single()["total"]

                # Calculate graph density
                # Density = actual_edges / possible_edges
                # For directed graph: possible_edges = n * (n - 1)
                if total_nodes > 1:
                    possible_edges = total_nodes * (total_nodes - 1)
                    graph_density = total_rels / possible_edges if possible_edges > 0 else 0.0
                else:
                    graph_density = 0.0

                return {
                    "node_counts": node_counts,
                    "relationship_counts": relationship_counts,
                    "total_nodes": total_nodes,
                    "total_relationships": total_rels,
                    "graph_density": round(graph_density, 4),
                    "last_updated": datetime.utcnow().isoformat(),
                }

        except Exception as e:
            logger.error(f"Error getting graph statistics: {e}")
            raise

    def health_check(self) -> Dict[str, Any]:
        """
        Perform graph health check.

        Checks:
        - Orphaned nodes (no relationships)
        - Nodes with missing chunk_ids
        - Connection status

        Returns:
            Health check results with warnings/errors
        """
        if not self.driver:
            return {
                "status": "error",
                "error": "Neo4J driver not initialized",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                # Check for orphaned nodes
                orphaned_query = """
                MATCH (n)
                WHERE NOT (n)--()
                RETURN count(n) AS orphaned_count
                """
                orphaned_count = session.run(orphaned_query).single()["orphaned_count"]

                # Check for nodes with missing chunk_ids
                broken_query = """
                MATCH (n)
                WHERE n.chunk_ids IS NULL OR size(n.chunk_ids) = 0
                RETURN count(n) AS broken_count
                """
                broken_count = session.run(broken_query).single()["broken_count"]

                # Determine health status
                warnings = []
                errors = []

                if orphaned_count > 100:
                    warnings.append(f"{orphaned_count} orphaned nodes detected")

                if broken_count > 0:
                    errors.append(f"{broken_count} nodes with missing chunk_ids")

                if errors:
                    status = "unhealthy"
                elif warnings:
                    status = "degraded"
                else:
                    status = "healthy"

                return {
                    "status": status,
                    "orphaned_nodes": orphaned_count,
                    "broken_references": broken_count,
                    "warnings": warnings,
                    "errors": errors,
                    "timestamp": datetime.utcnow().isoformat(),
                }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_entity_details(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific entity.

        Args:
            entity_id: Entity ID to lookup

        Returns:
            Entity details with properties and relationships
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                query = """
                MATCH (e {id: $entity_id})
                OPTIONAL MATCH (e)-[r]->(related)
                RETURN e, labels(e) AS labels,
                       collect({
                           type: type(r),
                           direction: 'outgoing',
                           target_id: related.id,
                           target_text: coalesce(related.text, related.name)
                       }) AS outgoing_rels
                """
                result = session.run(query, entity_id=entity_id)
                record = result.single()

                if not record:
                    return None

                entity_node = record["e"]
                labels = record["labels"]
                outgoing_rels = [r for r in record["outgoing_rels"] if r["type"] is not None]

                # Get incoming relationships
                incoming_query = """
                MATCH (source)-[r]->(e {id: $entity_id})
                RETURN collect({
                    type: type(r),
                    direction: 'incoming',
                    source_id: source.id,
                    source_text: coalesce(source.text, source.name)
                }) AS incoming_rels
                """
                incoming_result = session.run(incoming_query, entity_id=entity_id)
                incoming_rels = incoming_result.single()["incoming_rels"]

                # Combine properties
                properties = dict(entity_node)

                return {
                    "id": entity_id,
                    "labels": labels,
                    "properties": properties,
                    "relationships": {
                        "outgoing": outgoing_rels,
                        "incoming": incoming_rels,
                    },
                }

        except Exception as e:
            logger.error(f"Error getting entity details for {entity_id}: {e}")
            raise

    def get_visualization_data(
        self, entity_id: str, depth: int = 2
    ) -> Dict[str, Any]:
        """
        Get graph data for visualization (nodes and edges).

        Args:
            entity_id: Root entity ID
            depth: Traversal depth from root entity

        Returns:
            Nodes and edges for visualization (D3.js, Cytoscape.js, vis.js compatible)
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                query = f"""
                MATCH path = (root {{id: $entity_id}})-[*0..{depth}]-(node)
                WITH nodes(path) AS path_nodes, relationships(path) AS path_rels
                UNWIND path_nodes AS n
                WITH collect(DISTINCT {{
                    id: n.id,
                    label: coalesce(n.text, n.name, n.id),
                    type: labels(n)[0],
                    properties: properties(n)
                }}) AS nodes, path_rels
                UNWIND path_rels AS r
                RETURN nodes,
                       collect(DISTINCT {{
                           source: startNode(r).id,
                           target: endNode(r).id,
                           type: type(r)
                       }}) AS edges
                """
                result = session.run(query, entity_id=entity_id)
                record = result.single()

                if not record:
                    return {"nodes": [], "edges": []}

                return {
                    "nodes": record["nodes"],
                    "edges": record["edges"],
                }

        except Exception as e:
            logger.error(f"Error getting visualization data for {entity_id}: {e}")
            raise

    def search_entities(
        self, search_term: str, entity_types: Optional[List[str]] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search for entities by text/name.

        Args:
            search_term: Search query
            entity_types: Filter by entity types (optional)
            limit: Maximum results

        Returns:
            List of matching entities
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                if entity_types:
                    # Search with type filter
                    labels_filter = " OR ".join([f"'{t}' IN labels(e)" for t in entity_types])
                    query = f"""
                    MATCH (e)
                    WHERE ({labels_filter})
                      AND (toLower(e.text) CONTAINS toLower($search_term)
                           OR toLower(e.name) CONTAINS toLower($search_term))
                    RETURN e.id AS id,
                           labels(e) AS labels,
                           coalesce(e.text, e.name) AS text,
                           properties(e) AS properties
                    LIMIT $limit
                    """
                else:
                    # Search all entity types
                    query = """
                    MATCH (e)
                    WHERE toLower(e.text) CONTAINS toLower($search_term)
                       OR toLower(e.name) CONTAINS toLower($search_term)
                    RETURN e.id AS id,
                           labels(e) AS labels,
                           coalesce(e.text, e.name) AS text,
                           properties(e) AS properties
                    LIMIT $limit
                    """

                result = session.run(query, search_term=search_term, limit=limit)

                entities = []
                for record in result:
                    entities.append(
                        {
                            "id": record["id"],
                            "labels": record["labels"],
                            "text": record["text"],
                            "properties": dict(record["properties"]),
                        }
                    )

                return entities

        except Exception as e:
            logger.error(f"Error searching entities: {e}")
            raise

    def initialize_schema(self) -> None:
        """
        Initialize Neo4J schema with constraints and indexes.

        Creates:
        - Unique constraints on entity IDs
        - Indexes on frequently queried properties
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                # Create constraint on Entity.id
                session.run(
                    """
                    CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
                    FOR (e:Entity) REQUIRE e.id IS UNIQUE
                    """
                )

                # Create indexes on text/name properties for fast search
                session.run(
                    """
                    CREATE INDEX entity_text_index IF NOT EXISTS
                    FOR (e:Entity) ON (e.text)
                    """
                )

                session.run(
                    """
                    CREATE INDEX entity_name_index IF NOT EXISTS
                    FOR (e:Entity) ON (e.name)
                    """
                )

                logger.info("✓ Neo4J schema initialized (constraints and indexes created)")

        except Exception as e:
            logger.error(f"Error initializing schema: {e}")
            raise


# Singleton instance management
_graph_service: Optional[Neo4JGraphService] = None


def get_graph_service(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str = "neo4j",
) -> Neo4JGraphService:
    """
    Get singleton graph service instance.

    Args:
        neo4j_uri: Neo4J connection URI
        neo4j_user: Neo4J username
        neo4j_password: Neo4J password
        neo4j_database: Neo4J database name

    Returns:
        Neo4JGraphService instance
    """
    global _graph_service
    if _graph_service is None:
        _graph_service = Neo4JGraphService(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
        )
    return _graph_service
