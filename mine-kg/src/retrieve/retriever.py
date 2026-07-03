"""Гибридный ретрив: вектор находит старт -> Cypher-шаблоны обходят граф и фильтруют по числам.
Собирает контекст (чанки + подграф + провенанс) для синтеза ответа.
"""
from src.embeddings import get_embedder
from src.graph import queries as Q


def retrieve(session, question: str, slots: dict, top_k: int = 8) -> dict:
    embedder = get_embedder()
    geo = slots.get("geography") if slots.get("geography") != "unknown" else None
    year_from = slots.get("year_from")

    # 1) семантический старт
    qvec = embedder.embed_query(question)
    chunks = Q.vector_search(session, qvec, top_k=top_k, geography=geo, year_from=year_from)

    # 2) числовые ограничения -> точный поиск по графу
    constraint_hits = []
    for c in slots.get("constraints", []):
        constraint_hits += Q.find_by_constraint(
            session,
            param=c.get("param", ""),
            op=c.get("op", "eq"),
            value=c.get("value"),
            value_max=c.get("value_max"),
            geography=geo,
        )

    # 3) эксперименты/публикации для обзорных и list-запросов
    exp_pubs = []
    if slots.get("intent") in ("literature_review", "list_experiments"):
        kws = slots.get("materials", []) + slots.get("processes", [])
        if kws:
            exp_pubs = Q.find_experiments_publications(
                session, keywords=kws, year_from=year_from, geography=geo
            )

    # 4) собрать источники для цитирования (dedup по doc_id)
    sources = {}
    for ch in chunks:
        sources[ch["doc_id"]] = {"doc_id": ch["doc_id"], "geography": ch.get("geography"),
                                 "year": ch.get("year")}

    return {
        "chunks": chunks,
        "constraint_hits": constraint_hits,
        "exp_pubs": exp_pubs,
        "sources": list(sources.values()),
        "slots": slots,
    }
