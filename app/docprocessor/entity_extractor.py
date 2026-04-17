"""LLM-based entity and relationship extraction from document chunks.

Extracts entities (people, products, concepts, etc.) and their
relationships from text chunks using a cheap LLM. Results are stored
in the rag_entities and rag_relationships tables for Graph RAG.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.stdlib.get_logger()

_EXTRACTION_PROMPT = """Extract entities and relationships from this text.

Return a JSON object with:
- "entities": list of {{"name": "...", "type": "...", "description": "..."}}
  Types: person, organization, product, concept, location, event, technology
- "relationships": list of {{"source": "...", "target": "...", "type": "..."}}
  Types: uses, contains, related_to, part_of, created_by, depends_on

Text:
{text}

Return ONLY valid JSON. No explanation."""


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    description: str = ""


@dataclass
class ExtractedRelationship:
    source: str
    target: str
    relationship_type: str


@dataclass
class ExtractionOutput:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)


class EntityExtractor:
    """Extract entities and relationships from text chunks."""

    async def extract(self, chunk_text: str) -> ExtractionOutput:
        """Extract entities and relationships from a text chunk."""
        if not settings.RAG_GRAPH_ENABLED:
            return ExtractionOutput()

        try:
            from app.ai.gateway import ai_gateway

            response = await ai_gateway.complete(
                model=settings.RAG_CONTEXTUAL_MODEL,  # Cheap model
                messages=[{
                    "role": "user",
                    "content": _EXTRACTION_PROMPT.format(text=chunk_text[:3000]),
                }],
                max_tokens=500,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            return self._parse_response(content)

        except Exception:
            logger.debug("entity_extraction_failed", exc_info=True)
            return ExtractionOutput()

    def _parse_response(self, content: str) -> ExtractionOutput:
        """Parse LLM response into structured entities and relationships."""
        try:
            # Try to extract JSON from the response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            data = json.loads(content)

            entities = [
                ExtractedEntity(
                    name=e.get("name", "")[:500],
                    entity_type=e.get("type", "concept")[:100],
                    description=e.get("description", "")[:1000],
                )
                for e in data.get("entities", [])
                if e.get("name")
            ]

            relationships = [
                ExtractedRelationship(
                    source=r.get("source", "")[:500],
                    target=r.get("target", "")[:500],
                    relationship_type=r.get("type", "related_to")[:100],
                )
                for r in data.get("relationships", [])
                if r.get("source") and r.get("target")
            ]

            return ExtractionOutput(entities=entities, relationships=relationships)

        except (json.JSONDecodeError, KeyError, TypeError):
            logger.debug("entity_extraction_parse_failed", exc_info=True)
            return ExtractionOutput()

    async def store_extraction(
        self,
        output: ExtractionOutput,
        chunk_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Store extracted entities and relationships in the database."""
        if not output.entities:
            return

        entity_name_to_id: dict[str, str] = {}

        for entity in output.entities:
            # Upsert entity
            result = await db.execute(
                text("""
                    INSERT INTO rag_entities (id, tenant_id, name, entity_type, description)
                    VALUES (gen_random_uuid(), :tenant_id, :name, :entity_type, :description)
                    ON CONFLICT (tenant_id, name, entity_type) DO UPDATE
                    SET description = COALESCE(NULLIF(EXCLUDED.description, ''), rag_entities.description)
                    RETURNING id::text
                """),
                {
                    "tenant_id": str(tenant_id),
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "description": entity.description,
                },
            )
            row = result.one_or_none()
            if row:
                entity_name_to_id[entity.name] = row[0]

        for rel in output.relationships:
            source_id = entity_name_to_id.get(rel.source)
            target_id = entity_name_to_id.get(rel.target)
            if source_id and target_id:
                await db.execute(
                    text("""
                        INSERT INTO rag_relationships
                            (id, tenant_id, source_entity_id, target_entity_id,
                             relationship_type, chunk_id)
                        VALUES (gen_random_uuid(), :tenant_id, :source_id::uuid,
                                :target_id::uuid, :rel_type, :chunk_id)
                    """),
                    {
                        "tenant_id": str(tenant_id),
                        "source_id": source_id,
                        "target_id": target_id,
                        "rel_type": rel.relationship_type,
                        "chunk_id": str(chunk_id),
                    },
                )

        logger.info(
            "entities_stored",
            entities=len(output.entities),
            relationships=len(output.relationships),
            chunk_id=str(chunk_id),
        )


# Module-level singleton
entity_extractor = EntityExtractor()
