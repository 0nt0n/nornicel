"""Извлечение: чанк -> структурированный JSON по контракту (schema/ontology.py).

Использует structured output Yandex. Чекпоинтит результат по документам в data/processed/,
чтобы при обрыве не гонять корпус заново.
"""
import json
import os
from typing import List

import config
from schema.ontology import ChunkExtraction, EXTRACTION_JSON_SCHEMA
from src.yandex import chat_json
from src.extract.prompts import EXTRACT_SYSTEM, EXTRACT_USER_TMPL


def extract_chunk(chunk, model: str = None) -> ChunkExtraction:
    user = EXTRACT_USER_TMPL.format(
        lang=chunk.lang, doc_id=chunk.doc_id, page=chunk.page, text=chunk.text
    )
    raw = chat_json(
        system=EXTRACT_SYSTEM,
        user=user,
        schema_name="chunk_extraction",
        schema=EXTRACTION_JSON_SCHEMA,
        model=model or config.LLM_MODEL_MAIN,
    )
    try:
        return ChunkExtraction(**raw)
    except Exception:
        # если модель вернула частично невалидную структуру — не роняем прогон
        return ChunkExtraction()


def extract_document(doc_id: str, chunks: List, model: str = None, resume: bool = True) -> dict:
    """Извлекает все чанки одного документа. Возвращает {chunk_id: {chunk, extraction}}.
    Чекпоинт: data/processed/<doc_id>.json."""
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(config.PROCESSED_DIR, f"{doc_id}.json")

    done = {}
    if resume and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            done = json.load(f)

    for ch in chunks:
        if ch.chunk_id in done:
            continue
        ext = extract_chunk(ch, model=model)
        done[ch.chunk_id] = {"chunk": ch.dict(), "extraction": ext.model_dump()}
        # чекпоинтим после КАЖДОГО чанка — потеря прогона недопустима
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(done, f, ensure_ascii=False, indent=2)
    return done
