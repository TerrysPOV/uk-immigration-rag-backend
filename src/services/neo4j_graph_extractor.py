"""
Neo4J Graph Extractor - Entity and Relationship Extraction for Immigration RAG

Implements NEO4J-001 specification:
- Hybrid entity extraction (SpaCy NER + Regex + LLM)
- Relationship inference between entities
- Batch writing to Neo4J graph database
- Support for visa types, requirements, documents, organizations, countries

Architecture:
- SpaCy NER for general entities (organizations, locations, dates)
- Regex patterns for domain-specific entities (visa codes, document types)
- LLM-based extraction for complex structures (requirements, conditions, processes)
"""

import logging
import re
import hashlib
import json
from typing import List, Dict, Any, Tuple, Optional
from haystack import component, Document
from neo4j import GraphDatabase, Driver
import spacy
from spacy.language import Language

from src.services.openrouter_service import OpenRouterService

logger = logging.getLogger(__name__)


@component
class Neo4JGraphExtractor:
    """
    Extract entities and relationships from immigration documents.

    Uses hybrid approach:
    1. SpaCy NER for general entities (organizations, locations, dates)
    2. Regex patterns for domain-specific entities (visa codes, document types)
    3. LLM-based extraction for complex relationships (requirements, conditions)
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        spacy_model: str = "en_core_web_lg",
        llm_extractor_model: str = "openai/gpt-4o-mini",  # Via OpenRouter
        batch_size: int = 50,
        enable_llm_extraction: bool = True,
    ):
        """
        Initialize Neo4J graph extractor.

        Args:
            neo4j_uri: Neo4J connection URI (bolt://localhost:7687)
            neo4j_user: Neo4J username
            neo4j_password: Neo4J password
            neo4j_database: Neo4J database name (default: neo4j)
            spacy_model: SpaCy model name (default: en_core_web_lg)
            llm_extractor_model: LLM model for complex extraction
            batch_size: Batch size for Neo4J writes
            enable_llm_extraction: Enable LLM-based extraction (default: True)
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.batch_size = batch_size
        self.enable_llm_extraction = enable_llm_extraction
        self.llm_model = llm_extractor_model

        # Initialize Neo4J driver
        self.driver: Optional[Driver] = None
        self._connect_neo4j()

        # Initialize SpaCy
        try:
            self.nlp: Optional[Language] = spacy.load(spacy_model)
            logger.info(f"✓ SpaCy model loaded: {spacy_model}")
        except OSError:
            logger.warning(
                f"SpaCy model {spacy_model} not found. "
                "Entity extraction will use regex only. "
                "Install with: python -m spacy download en_core_web_lg"
            )
            self.nlp = None

        # Initialize OpenRouter service for LLM extraction
        if self.enable_llm_extraction:
            self.openrouter_service = OpenRouterService()
            logger.info(f"✓ LLM extractor initialized: {llm_extractor_model}")

        # Domain-specific regex patterns
        self.patterns = {
            "visa_type": re.compile(
                r"(Skilled Worker|Student|Family|Tourist|Entrepreneur|Innovator|Graduate|Health and Care Worker|"
                r"Global Talent|Start-up|Intra-Company Transfer|Minister of Religion|Sportsperson|Representative of an Overseas Business|"
                r"Temporary Worker|Seasonal Worker|Creative Worker|Charity Worker|Religious Worker|"
                r"Youth Mobility|Parent|Partner|Child|Adult Dependent Relative|Settlement|Indefinite Leave to Remain|British Citizenship)\s*(?:visa|route)?",
                re.IGNORECASE,
            ),
            "visa_code": re.compile(r"\b(T[1-5]|PBS)\b"),  # e.g., T2, T4, T5, PBS
            "document_type": re.compile(
                r"(passport|birth certificate|marriage certificate|divorce certificate|death certificate|"
                r"bank statement|payslip|P60|employment contract|sponsor licence|certificate of sponsorship|CAS|"
                r"degree certificate|academic transcript|English language test|IELTS|TOEFL|PTE|SELT|"
                r"tuberculosis test|TB certificate|police certificate|criminal record check|DBS check|"
                r"tenancy agreement|mortgage statement|utility bill|council tax bill|NHS registration|"
                r"travel itinerary|flight booking|accommodation booking)",
                re.IGNORECASE,
            ),
            "requirement_indicator": re.compile(
                r"(must|required to|need to|should|have to|necessary to|mandatory)\s+(provide|submit|demonstrate|show|have|hold|meet|satisfy)",
                re.IGNORECASE,
            ),
            "time_period": re.compile(r"\d+\s*(day|week|month|year|hour)s?", re.IGNORECASE),
            "money": re.compile(r"£\d+(?:,\d{3})*(?:\.\d{2})?"),
        }

        logger.info(f"Neo4JGraphExtractor initialized (database: {neo4j_database})")

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

    @component.output_types(entities=List[Dict[str, Any]], relationships=List[Tuple[str, str, str]])
    def run(self, documents: List[Document]) -> Dict[str, Any]:
        """
        Extract entities and relationships from documents.

        Args:
            documents: List of Haystack Document objects with content and metadata

        Returns:
            entities: List of extracted entities with types and properties
            relationships: List of (source_id, relationship_type, target_id) tuples
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        all_entities = []
        all_relationships = []

        logger.info(f"Extracting entities from {len(documents)} documents...")

        for doc in documents:
            try:
                # Step 1: SpaCy NER extraction
                spacy_entities = self._extract_spacy_entities(doc)

                # Step 2: Regex pattern extraction
                pattern_entities = self._extract_pattern_entities(doc)

                # Step 3: LLM-based extraction for complex structures
                llm_entities = []
                if self.enable_llm_extraction:
                    llm_entities = self._extract_llm_entities(doc)

                # Combine all entities
                doc_entities = spacy_entities + pattern_entities + llm_entities

                # Step 4: Relationship extraction
                relationships = self._extract_relationships(doc, doc_entities)

                all_entities.extend(doc_entities)
                all_relationships.extend(relationships)

            except Exception as e:
                logger.error(f"Error extracting from document {doc.id}: {e}")
                continue

        # Step 5: Write to Neo4J
        if all_entities or all_relationships:
            self._write_to_neo4j(all_entities, all_relationships)

        logger.info(
            f"Extracted {len(all_entities)} entities and {len(all_relationships)} relationships"
        )

        return {"entities": all_entities, "relationships": all_relationships}

    def _extract_spacy_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """Extract named entities using SpaCy."""
        if not self.nlp:
            return []

        entities = []

        try:
            # Limit content to 1M chars to avoid memory issues
            content = doc.content[:1000000] if doc.content else ""
            spacy_doc = self.nlp(content)

            for ent in spacy_doc.ents:
                if ent.label_ in ["ORG", "GPE", "DATE", "MONEY", "PERSON", "LOC"]:
                    entity_id = self._generate_entity_id(doc.id, ent.text, ent.label_)
                    entities.append(
                        {
                            "id": entity_id,
                            "type": self._map_spacy_label(ent.label_),
                            "text": ent.text,
                            "name": ent.text,
                            "chunk_ids": [doc.id],
                            "confidence": 0.8,  # SpaCy NER baseline confidence
                            "source": "spacy",
                        }
                    )

        except Exception as e:
            logger.error(f"SpaCy extraction error for document {doc.id}: {e}")

        return entities

    def _extract_pattern_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """Extract domain-specific entities using regex patterns."""
        entities = []
        content = doc.content if doc.content else ""

        for entity_type, pattern in self.patterns.items():
            if entity_type == "requirement_indicator":
                continue  # This is used for relationship extraction, not entities

            try:
                matches = pattern.finditer(content)
                for match in matches:
                    text = match.group(0).strip()
                    entity_id = self._generate_entity_id(doc.id, text, entity_type)

                    entities.append(
                        {
                            "id": entity_id,
                            "type": entity_type,
                            "text": text,
                            "name": text,
                            "chunk_ids": [doc.id],
                            "confidence": 0.9,  # High confidence for pattern matches
                            "source": "regex",
                        }
                    )

            except Exception as e:
                logger.error(f"Pattern extraction error for {entity_type}: {e}")

        return entities

    def _extract_llm_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """
        Use LLM to extract complex entities (requirements, conditions, processes).

        Uses OpenRouter API with structured JSON extraction prompts.
        """
        entities = []
        content = doc.content[:4000] if doc.content else ""  # Limit to 4k chars for cost

        if not content.strip():
            return entities

        # LLM extraction prompt
        prompt = f"""Extract immigration visa requirements and conditions from this UK immigration document text.

Text: {content}

Return ONLY valid JSON with this exact structure (no markdown, no explanations):
{{
    "requirements": [
        {{"text": "requirement description", "category": "financial|documents|english|health|other", "mandatory": true}}
    ],
    "conditions": [
        {{"text": "condition description", "applies_to": ["visa type names"]}}
    ],
    "processes": [
        {{"name": "process name", "steps": ["step 1", "step 2"], "duration": "estimate or null"}}
    ]
}}

If no entities found, return: {{"requirements": [], "conditions": [], "processes": []}}"""

        try:
            # Call LLM via OpenRouter
            response_text = self._call_llm(prompt)

            # Parse JSON response
            try:
                response_data = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", response_text, re.DOTALL)
                if json_match:
                    response_data = json.loads(json_match.group(1))
                else:
                    logger.warning(f"Failed to parse LLM response as JSON: {response_text[:200]}")
                    return entities

            # Process requirements
            for req in response_data.get("requirements", []):
                entity_id = self._generate_entity_id(doc.id, req["text"], "requirement")
                entities.append(
                    {
                        "id": entity_id,
                        "type": "requirement",
                        "text": req["text"],
                        "category": req.get("category", "other"),
                        "mandatory": req.get("mandatory", True),
                        "chunk_ids": [doc.id],
                        "confidence": 0.7,  # LLM extraction has moderate confidence
                        "source": "llm",
                    }
                )

            # Process conditions
            for cond in response_data.get("conditions", []):
                entity_id = self._generate_entity_id(doc.id, cond["text"], "condition")
                entities.append(
                    {
                        "id": entity_id,
                        "type": "condition",
                        "text": cond["text"],
                        "applies_to": cond.get("applies_to", []),
                        "chunk_ids": [doc.id],
                        "confidence": 0.7,
                        "source": "llm",
                    }
                )

            # Process processes
            for proc in response_data.get("processes", []):
                entity_id = self._generate_entity_id(doc.id, proc["name"], "process")
                entities.append(
                    {
                        "id": entity_id,
                        "type": "process",
                        "name": proc["name"],
                        "text": proc["name"],
                        "steps": proc.get("steps", []),
                        "duration_estimate": proc.get("duration"),
                        "chunk_ids": [doc.id],
                        "confidence": 0.7,
                        "source": "llm",
                    }
                )

        except Exception as e:
            logger.error(f"LLM extraction error for document {doc.id}: {e}")

        return entities

    def _extract_relationships(
        self, doc: Document, entities: List[Dict[str, Any]]
    ) -> List[Tuple[str, str, str]]:
        """
        Extract relationships between entities.

        Relationships extracted:
        - VisaType → Requirement (REQUIRES)
        - Requirement → Document_Type (SATISFIED_BY)
        - VisaType → VisaType (CAN_TRANSITION_TO)
        - Document → Entity (CONTAINS_ENTITY)
        """
        relationships = []
        content = doc.content if doc.content else ""

        # Split into sentences for co-occurrence analysis
        sentences = content.split(".")

        # Group entities by type
        visa_entities = [e for e in entities if e["type"] == "visa_type"]
        req_entities = [e for e in entities if e["type"] == "requirement"]
        doc_type_entities = [e for e in entities if e["type"] == "document_type"]

        # Heuristic 1: If visa type and requirement appear in same sentence, create REQUIRES relationship
        for sent in sentences:
            sent_lower = sent.lower()

            visa_in_sent = [v for v in visa_entities if v["text"].lower() in sent_lower]
            req_in_sent = [r for r in req_entities if r["text"].lower() in sent_lower]

            for visa in visa_in_sent:
                for req in req_in_sent:
                    relationships.append((visa["id"], "REQUIRES", req["id"]))

        # Heuristic 2: If requirement and document type appear in same sentence, create SATISFIED_BY
        for sent in sentences:
            sent_lower = sent.lower()

            req_in_sent = [r for r in req_entities if r["text"].lower() in sent_lower]
            doc_in_sent = [d for d in doc_type_entities if d["text"].lower() in sent_lower]

            for req in req_in_sent:
                for doc_type in doc_in_sent:
                    relationships.append((req["id"], "SATISFIED_BY", doc_type["id"]))

        # Document provenance relationships: All entities are contained in their source document
        for entity in entities:
            relationships.append((doc.id, "CONTAINS_ENTITY", entity["id"]))

        return relationships

    def _write_to_neo4j(
        self, entities: List[Dict[str, Any]], relationships: List[Tuple[str, str, str]]
    ) -> None:
        """Batch write entities and relationships to Neo4J."""
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                # Create entities in batches
                for i in range(0, len(entities), self.batch_size):
                    batch = entities[i : i + self.batch_size]
                    session.execute_write(self._create_entity_batch, batch)

                logger.info(f"Wrote {len(entities)} entities to Neo4J")

                # Create relationships in batches
                for i in range(0, len(relationships), self.batch_size):
                    batch = relationships[i : i + self.batch_size]
                    session.execute_write(self._create_relationship_batch, batch)

                logger.info(f"Wrote {len(relationships)} relationships to Neo4J")

        except Exception as e:
            logger.error(f"Neo4J write error: {e}")
            raise

    @staticmethod
    def _create_entity_batch(tx, entities: List[Dict[str, Any]]) -> None:
        """Cypher query to create entity nodes with dynamic labels."""
        # Note: Using MERGE to avoid duplicates, SET to update properties
        query = """
        UNWIND $entities AS entity
        MERGE (n:Entity {id: entity.id})
        SET n += entity
        WITH n, entity.type AS type
        CALL apoc.create.addLabels(n, [type]) YIELD node
        RETURN count(node) as created
        """
        result = tx.run(query, entities=entities)
        count = result.single()["created"]
        logger.debug(f"Created/updated {count} entities in batch")

    @staticmethod
    def _create_relationship_batch(tx, relationships: List[Tuple[str, str, str]]) -> None:
        """Cypher query to create relationships dynamically."""
        # Format relationships for Cypher
        rels_formatted = [
            {"source": src, "type": rel_type, "target": tgt} for src, rel_type, tgt in relationships
        ]

        query = """
        UNWIND $rels AS rel
        MATCH (a {id: rel.source})
        MATCH (b {id: rel.target})
        CALL apoc.create.relationship(a, rel.type, {}, b) YIELD rel AS r
        RETURN count(r) as created
        """
        result = tx.run(query, rels=rels_formatted)
        count = result.single()["created"]
        logger.debug(f"Created {count} relationships in batch")

    def _call_llm(self, prompt: str) -> str:
        """Call LLM via OpenRouter API."""
        try:
            response = self.openrouter_service.generate_sync(
                prompt=prompt, model=self.llm_model, temperature=0.1, max_tokens=2000
            )
            return response
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return '{"requirements": [], "conditions": [], "processes": []}'

    def _map_spacy_label(self, label: str) -> str:
        """Map SpaCy entity labels to graph node types."""
        mapping = {
            "ORG": "organization",
            "GPE": "country",
            "LOC": "location",
            "DATE": "date",
            "MONEY": "monetary_value",
            "PERSON": "person",
        }
        return mapping.get(label, label.lower())

    def _generate_entity_id(self, doc_id: str, text: str, entity_type: str) -> str:
        """Generate deterministic entity ID based on content."""
        # Use hash of text + type for deterministic IDs
        content_hash = hashlib.md5(f"{text}:{entity_type}".encode()).hexdigest()[:12]
        return f"{entity_type}_{content_hash}"


# Singleton instance management
_graph_extractor: Optional[Neo4JGraphExtractor] = None


def get_graph_extractor(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str = "neo4j",
) -> Neo4JGraphExtractor:
    """
    Get singleton graph extractor instance.

    Args:
        neo4j_uri: Neo4J connection URI
        neo4j_user: Neo4J username
        neo4j_password: Neo4J password
        neo4j_database: Neo4J database name

    Returns:
        Neo4JGraphExtractor instance
    """
    global _graph_extractor
    if _graph_extractor is None:
        _graph_extractor = Neo4JGraphExtractor(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
        )
    return _graph_extractor
