"""Извлечение: чанк -> структурированный JSON по контракту (schema/ontology.py).

Использует structured output Yandex. Чекпоинтит результат по документам в data/processed/,
чтобы при обрыве не гонять корпус заново.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import config
from schema.ontology import ChunkExtraction, EXTRACTION_JSON_SCHEMA
from src.yandex import chat_json
from src.extract.prompts import (EXTRACT_SYSTEM, EXTRACT_USER_TMPL,
                                 EXTRACT_RETRY_SYSTEM, EXTRACT_RETRY_USER_TMPL)

def extract_chunk(chunk, model: str = None) -> ChunkExtraction:
    user = EXTRACT_USER_TMPL.format(
        lang=chunk.lang, doc_id=chunk.doc_id, page=chunk.page, text=chunk.text
    )
    try:
        raw = chat_json(
            system=EXTRACT_SYSTEM,
            user=user,
            schema_name="chunk_extraction",
            schema=EXTRACTION_JSON_SCHEMA,
            model=model or config.LLM_MODEL_MAIN,
        )
    except Exception as e:
        print(f"[extract] запрос к модели упал для {chunk.chunk_id}: {e!r}")
        return ChunkExtraction()

    try:
        result = ChunkExtraction(**raw)
    except Exception as e:
        print(f"[extract] невалидный JSON от модели для {chunk.chunk_id}: {e} | raw={str(raw)[:300]}")
        return ChunkExtraction()

    if not result.entities and len(chunk.text.strip()) > 100:
        print(f"[extract] retry для {chunk.chunk_id}: пустой результат, текст {len(chunk.text)} символов")
        retry_user = EXTRACT_RETRY_USER_TMPL.format(
            lang=chunk.lang, doc_id=chunk.doc_id, page=chunk.page, text=chunk.text
        )
        try:
            raw2 = chat_json(
                system=EXTRACT_RETRY_SYSTEM,
                user=retry_user,
                schema_name="chunk_extraction",
                schema=EXTRACTION_JSON_SCHEMA,
                model=model or config.LLM_MODEL_MAIN,
            )
            retry_result = ChunkExtraction(**raw2)
            if retry_result.entities:
                print(f"[extract] retry для {chunk.chunk_id}: извлечено {len(retry_result.entities)} сущностей")
                return retry_result
        except Exception as e:
            print(f"[extract] retry тоже не сработал для {chunk.chunk_id}: {e!r}")

    return result

def _finalize_metadata(chunks: List, done: dict) -> None:
    """Год/география должны быть едиными для всего документа, а не гадаться независимо
    по каждому чанку (на большинстве чанков в тексте просто нет даты/страны — LLM тогда
    честно возвращает unknown/None). Приоритет года: путь/имя файла (надёжнее всего) ->
    текст документа (LLM) -> встроенные метаданные файла (PDF Info / OOXML) как запасной
    вариант. География: путь -> LLM."""
    struct_year = next((ch.path_year for ch in chunks if ch.path_year), None)
    struct_geo = next((ch.path_geo for ch in chunks if ch.path_geo), None)
    file_meta_year = next((getattr(ch, "meta_year", None) for ch in chunks
                            if getattr(ch, "meta_year", None)), None)

    llm_year = next((v["extraction"]["metadata"].get("year")
                      for v in done.values() if v["extraction"]["metadata"].get("year")), None)
    llm_geo = next((v["extraction"]["metadata"].get("geography")
                     for v in done.values()
                     if v["extraction"]["metadata"].get("geography") not in (None, "unknown")), None)

    doc_year = struct_year or llm_year or file_meta_year
    doc_geo = struct_geo or llm_geo or "unknown"

    for v in done.values():
        m = v["extraction"]["metadata"]
        if not m.get("year"):
            m["year"] = doc_year
        if not m.get("geography") or m.get("geography") == "unknown":
            m["geography"] = doc_geo

def extract_document(doc_id: str, chunks: List, model: str = None, resume: bool = True) -> dict:
    """Извлекает все чанки одного документа параллельно (config.MAX_WORKERS воркеров).
    Возвращает {chunk_id: {chunk, extraction}}. Чекпоинт: data/processed/<doc_id>.json."""
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(config.PROCESSED_DIR, f"{doc_id}.json")

    done = {}
    if resume and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            done = json.load(f)

    todo = [ch for ch in chunks if ch.chunk_id not in done]

    lock = threading.Lock()

    def _checkpoint():
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(done, f, ensure_ascii=False, indent=2)

    if todo:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futures = {pool.submit(extract_chunk, ch, model): ch for ch in todo}
            for future in as_completed(futures):
                ch = futures[future]
                ext = future.result()
                with lock:
                    done[ch.chunk_id] = {"chunk": ch.dict(), "extraction": ext.model_dump()}
                    _checkpoint()

    if done:
        _finalize_metadata(chunks, done)
        _checkpoint()
    return done
