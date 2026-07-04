"""Гибридный ретрив: вектор находит старт -> Cypher-шаблоны обходят граф и фильтруют по числам.
Собирает контекст (чанки + подграф + провенанс) для синтеза ответа.
"""
from src.embeddings import get_embedder
from src.graph import queries as Q

def retrieve(session, question: str, slots: dict, top_k: int = 8) -> dict:
    embedder = get_embedder()
    geo = slots.get("geography") if slots.get("geography") != "unknown" else None
    year_from = slots.get("year_from")

    qvec = embedder.embed_query(question)
    chunks = Q.vector_search(session, qvec, top_k=top_k, geography=geo, year_from=year_from)

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

    exp_pubs = []
    if slots.get("intent") in ("literature_review", "list_experiments"):
        kws = slots.get("materials", []) + slots.get("processes", [])
        if kws:
            exp_pubs = Q.find_experiments_publications(
                session, keywords=kws, year_from=year_from, geography=geo
            )

    sources = {}
    for ch in chunks:
        sources[ch["doc_id"]] = {"doc_id": ch["doc_id"], "geography": ch.get("geography"),
                                 "year": ch.get("year")}

    comparison_chunks = None
    if slots.get("comparison"):
        comparison_chunks = {
            "RU": Q.vector_search(session, qvec, top_k=top_k, geography="RU", year_from=year_from),
            "foreign": Q.vector_search(session, qvec, top_k=top_k, geography="foreign", year_from=year_from),
        }

    gaps = Q.find_gaps(session, limit=10)

    chunk_ids = [ch["chunk_id"] for ch in chunks]
    entities = Q.entities_for_chunks(session, chunk_ids)
    entity_keys = [e["key"] for e in entities]
    subgraph_edges = Q.neighborhood(session, entity_keys, hops=1) if entity_keys else []

    return {
        "chunks": chunks,
        "constraint_hits": constraint_hits,
        "exp_pubs": exp_pubs,
        "sources": list(sources.values()),
        "slots": slots,
        "comparison_chunks": comparison_chunks,
        "gaps": gaps,
        "entities": entities,
        "subgraph_edges": subgraph_edges,
    }
