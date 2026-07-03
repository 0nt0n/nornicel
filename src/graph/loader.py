"""Загрузка извлечённого JSON в Neo4j.

Модель графа:
  (:Chunk {chunk_id, text, doc_id, page, lang, geography, year, confidence, doc_type, embedding})
  (:Entity:<Type> {key, name_ru, name_en, canonical, geography})   key = canonical|name (для дедупа)
  (:Constraint {param, op, value_min, value_max, unit, condition})
  (Chunk)-[:MENTIONS]->(Entity)
  (Entity)-[:REL {type, evidence}]->(Entity)          type из RELATION_TYPES
  (Entity)-[:HAS_CONSTRAINT]->(Constraint)-[:FROM_CHUNK]->(Chunk)
"""
from neo4j import GraphDatabase

import config


def get_driver():
    return GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def _entity_key(e: dict) -> str:
    return (e.get("canonical") or e.get("name_en") or e.get("name_ru") or e.get("id")).strip().lower()


def load_chunk(session, chunk: dict, extraction: dict, embedding):
    meta = extraction.get("metadata", {}) or {}
    # 1) узел чанка + эмбеддинг
    session.run(
        """
        MERGE (c:Chunk {chunk_id: $chunk_id})
        SET c.text=$text, c.doc_id=$doc_id, c.page=$page, c.lang=$lang,
            c.geography=$geo, c.year=$year, c.confidence=$conf, c.doc_type=$doc_type,
            c.embedding=$emb
        """,
        chunk_id=chunk["chunk_id"], text=chunk["text"], doc_id=chunk["doc_id"],
        page=chunk["page"], lang=chunk["lang"],
        geo=meta.get("geography", "unknown"), year=meta.get("year"),
        conf=meta.get("confidence", "medium"), doc_type=chunk.get("doc_type", "unknown"),
        emb=embedding,
    )

    # 2) сущности (дедуп по key) + связь MENTIONS
    localid_to_key = {}
    for e in extraction.get("entities", []):
        key = _entity_key(e)
        localid_to_key[e["id"]] = key
        etype = e.get("type", "Entity")
        session.run(
            f"""
            MERGE (x:Entity {{key: $key}})
            SET x:{etype}, x.name_ru=$ru, x.name_en=$en, x.canonical=$can, x.geography=$geo
            WITH x
            MATCH (c:Chunk {{chunk_id: $chunk_id}})
            MERGE (c)-[:MENTIONS]->(x)
            """,
            key=key, ru=e.get("name_ru", ""), en=e.get("name_en", ""),
            can=e.get("canonical", ""), geo=meta.get("geography", "unknown"),
            chunk_id=chunk["chunk_id"],
        )

    # 3) связи между сущностями
    for r in extraction.get("relations", []):
        sk, tk = localid_to_key.get(r["source_id"]), localid_to_key.get(r["target_id"])
        if not sk or not tk:
            continue
        session.run(
            """
            MATCH (a:Entity {key:$sk}), (b:Entity {key:$tk})
            MERGE (a)-[rel:REL {type:$type}]->(b)
            SET rel.evidence=$ev
            """,
            sk=sk, tk=tk, type=r.get("type", "related"), ev=r.get("evidence", ""),
        )

    # 4) числовые ограничения + провенанс
    for c in extraction.get("constraints", []):
        ek = localid_to_key.get(c["entity_id"])
        if not ek:
            continue
        session.run(
            """
            MATCH (e:Entity {key:$ek})
            MATCH (ch:Chunk {chunk_id:$chunk_id})
            CREATE (con:Constraint {param:$param, op:$op, value_min:$vmin,
                                    value_max:$vmax, unit:$unit, condition:$cond})
            MERGE (e)-[:HAS_CONSTRAINT]->(con)
            MERGE (con)-[:FROM_CHUNK]->(ch)
            """,
            ek=ek, chunk_id=chunk["chunk_id"], param=c.get("param", ""),
            op=c.get("op", "eq"), vmin=c.get("value_min"), vmax=c.get("value_max"),
            unit=c.get("unit", ""), cond=c.get("condition", ""),
        )


def load_processed(session, processed: dict, embedder):
    """processed = {chunk_id: {chunk, extraction}} (как в data/processed/<doc>.json)."""
    items = list(processed.values())
    texts = [it["chunk"]["text"] for it in items]
    embs = embedder.embed_documents(texts)   # батч-эмбеддинги
    for it, emb in zip(items, embs):
        load_chunk(session, it["chunk"], it["extraction"], emb)
