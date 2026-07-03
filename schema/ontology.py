"""КОНТРАКТ проекта. Единая точка правды для формы извлечения.
Меняется ТОЛЬКО по согласованию всей команды — от неё зависят все модули.

Онтология из ТЗ:
  Сущности: Material, Process, Equipment, Property, Experiment, Publication, Expert, Facility
  Связи:    uses_material, operates_at_condition, produces_output, described_in, validated_by, contradicts
  + числовые ограничения (концентрации, температуры, скорости, ТЭП) — критичный дифференциатор.
"""
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

ENTITY_TYPES = [
    "Material", "Process", "Equipment", "Property",
    "Experiment", "Publication", "Expert", "Facility",
]
RELATION_TYPES = [
    "uses_material", "operates_at_condition", "produces_output",
    "described_in", "validated_by", "contradicts",
]
OPS = ["le", "ge", "eq", "range"]  # <=, >=, =, диапазон [min..max]
GEO = ["RU", "foreign", "unknown"]
CONFIDENCE = ["high", "medium", "low"]


# --- Pydantic-модели (валидация после парсинга ответа LLM) ---
class Entity(BaseModel):
    id: str = Field(description="Локальный id в пределах чанка, напр. e1")
    type: str = Field(description="Один из ENTITY_TYPES")
    name_ru: str = ""
    name_en: str = ""
    canonical: str = Field("", description="Канонический термин для сведе́ния синонимов RU<->EN")


class Relation(BaseModel):
    source_id: str
    target_id: str
    type: str = Field(description="Один из RELATION_TYPES")
    evidence: str = Field("", description="Фрагмент текста, подтверждающий связь")


class Constraint(BaseModel):
    entity_id: str
    param: str = Field(description="Параметр: sulfates, temperature, flow_rate, capacity, capex ...")
    op: str = Field(description="le|ge|eq|range")
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    unit: str = ""
    condition: str = Field("", description="Контекст условия, напр. 'холодный климат'")


class Metadata(BaseModel):
    lang: str = "ru"
    geography: str = "unknown"       # RU | foreign | unknown
    year: Optional[int] = None
    confidence: str = "medium"       # high | medium | low


class ChunkExtraction(BaseModel):
    entities: List[Entity] = []
    relations: List[Relation] = []
    constraints: List[Constraint] = []
    metadata: Metadata = Metadata()


# --- Явная JSON-схема для response_format (надёжнее, чем авто-экспорт pydantic) ---
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string", "enum": ENTITY_TYPES},
                    "name_ru": {"type": "string"},
                    "name_en": {"type": "string"},
                    "canonical": {"type": "string"},
                },
                "required": ["id", "type", "name_ru", "name_en", "canonical"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "type": {"type": "string", "enum": RELATION_TYPES},
                    "evidence": {"type": "string"},
                },
                "required": ["source_id", "target_id", "type", "evidence"],
            },
        },
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "param": {"type": "string"},
                    "op": {"type": "string", "enum": OPS},
                    "value_min": {"type": ["number", "null"]},
                    "value_max": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                },
                "required": ["entity_id", "param", "op", "value_min", "value_max", "unit", "condition"],
            },
        },
        "metadata": {
            "type": "object",
            "properties": {
                "lang": {"type": "string"},
                "geography": {"type": "string", "enum": GEO},
                "year": {"type": ["integer", "null"]},
                "confidence": {"type": "string", "enum": CONFIDENCE},
            },
            "required": ["lang", "geography", "year", "confidence"],
        },
    },
    "required": ["entities", "relations", "constraints", "metadata"],
}


# --- Схема для роутера запросов (NL -> структурные слоты) ---
QUERY_SLOTS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "description": "literature_review | find_solutions | compare | list_experiments | other"},
        "materials": {"type": "array", "items": {"type": "string"}},
        "processes": {"type": "array", "items": {"type": "string"}},
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "op": {"type": "string", "enum": OPS},
                    "value": {"type": ["number", "null"]},
                    "value_max": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                },
                "required": ["param", "op", "value", "value_max", "unit"],
            },
        },
        "geography": {"type": "string", "enum": GEO},
        "year_from": {"type": ["integer", "null"]},
        "year_to": {"type": ["integer", "null"]},
        "comparison": {"type": "boolean"},
    },
    "required": ["intent", "materials", "processes", "constraints", "geography", "year_from", "year_to", "comparison"],
}
