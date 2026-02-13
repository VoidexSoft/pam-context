"""Entity extractor — uses LLM to extract structured entities from text segments."""

from __future__ import annotations

import json
import uuid

import structlog
from anthropic import AsyncAnthropic

from pam.common.config import settings
from pam.ingestion.extractors.schemas import (
    EXTRACTION_SCHEMAS,
    ExtractedEntityData,
)

logger = structlog.get_logger()

EXTRACTION_PROMPT = """You are an entity extraction system. Extract structured business entities from the given text.

For each entity you find, output a JSON object with:
- "entity_type": one of {entity_types}
- "entity_data": the extracted fields
- "confidence": 0.0 to 1.0 (how confident you are this is a real entity)

Entity schemas:
{schema_descriptions}

Output a JSON array of extracted entities. If no entities are found, output an empty array [].
Only extract entities that are clearly present in the text — do not infer or guess.

Text to analyze:
---
{text}
---

Output (JSON array only, no other text):"""


class EntityExtractor:
    """Extracts structured business entities from text using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.agent_model

    async def extract_from_text(
        self,
        text: str,
        segment_id: uuid.UUID | None = None,
        entity_types: list[str] | None = None,
    ) -> list[ExtractedEntityData]:
        """Extract entities from a text segment.

        Args:
            text: The text to extract entities from.
            segment_id: The source segment ID for grounding.
            entity_types: Optional list of entity types to extract. Defaults to all.

        Returns:
            List of extracted entities.
        """
        if not text.strip():
            return []

        types = entity_types or list(EXTRACTION_SCHEMAS.keys())
        schema_desc = "\n".join(
            f"- {name}: {info['description']}"
            for name, info in EXTRACTION_SCHEMAS.items()
            if name in types
        )

        prompt = EXTRACTION_PROMPT.format(
            entity_types=", ".join(types),
            schema_descriptions=schema_desc,
            text=text[:4000],  # Limit input length
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text.strip()  # type: ignore[union-attr]
            # Extract JSON array from response
            entities_raw = json.loads(raw_text)

            if not isinstance(entities_raw, list):
                entities_raw = [entities_raw]

            results = []
            for raw in entities_raw:
                entity_type = raw.get("entity_type", "")
                if entity_type not in EXTRACTION_SCHEMAS:
                    continue

                # Validate against schema
                schema_entry = EXTRACTION_SCHEMAS[entity_type]
                schema_model = schema_entry["model"]
                try:
                    validated = schema_model(**raw.get("entity_data", {}))
                    results.append(
                        ExtractedEntityData(
                            entity_type=entity_type,
                            entity_data=validated.model_dump(),
                            confidence=float(raw.get("confidence", 0.5)),
                            source_segment_id=segment_id,
                            source_text=text[:500],
                        )
                    )
                except Exception:
                    logger.debug("entity_validation_failed", entity_type=entity_type, raw=raw)
                    continue

            logger.info("entities_extracted", count=len(results), types=[e.entity_type for e in results])
            return results

        except json.JSONDecodeError:
            logger.warning("entity_extraction_json_parse_failed")
            return []
        except Exception:
            logger.exception("entity_extraction_failed")
            return []

    async def extract_from_segments(
        self,
        segments: list[dict],
        entity_types: list[str] | None = None,
    ) -> list[ExtractedEntityData]:
        """Extract entities from multiple segments.

        Args:
            segments: List of dicts with 'id' and 'content' keys.
            entity_types: Optional filter for entity types.

        Returns:
            All extracted entities across all segments.
        """
        all_entities = []
        for seg in segments:
            entities = await self.extract_from_text(
                text=seg["content"],
                segment_id=seg.get("id"),
                entity_types=entity_types,
            )
            all_entities.extend(entities)

        logger.info("batch_extraction_complete", segments=len(segments), entities=len(all_entities))
        return all_entities
