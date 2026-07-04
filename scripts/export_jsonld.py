"""Экспорт графа знаний в JSON-LD (RDF-совместимый формат, принцип FAIR).

Онтология проекта (schema/ontology.py) отображается в JSON-LD @context:
типы сущностей — классы, связи — свойства. Результат можно загрузить в любой
RDF-инструмент (Apache Jena, GraphDB) или опубликовать как Linked Data.

Запуск:
    python scripts/export_jsonld.py                      # -> exports/knowledge_graph.jsonld
    python scripts/export_jsonld.py --out my_export.jsonld
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph.loader import get_driver
from schema.ontology import ENTITY_TYPES, RELATION_TYPES

BASE_IRI = "https://minekg.example.org/"

CONTEXT = {
    "@vocab": BASE_IRI + "ontology#",
    "name_ru": {"@id": BASE_IRI + "ontology#name_ru", "@language": "ru"},
    "name_en": {"@id": BASE_IRI + "ontology#name_en", "@language": "en"},
    "mentionedIn": {"@id": BASE_IRI + "ontology#mentionedIn", "@type": "@id"},
    **{rel: {"@id": BASE_IRI + f"ontology#{rel}", "@type": "@id"}
       for rel in RELATION_TYPES},
}

def export(session):
    graph = []

    rows = session.run(
        """
        MATCH (e:Entity)
        RETURN e.key AS key, e.name_ru AS name_ru, e.name_en AS name_en,
               e.canonical AS canonical, e.geography AS geography, labels(e) AS labels
        """
    )
    for r in rows:
        etype = next((l for l in r["labels"] if l in ENTITY_TYPES), "Entity")
        node = {
            "@id": BASE_IRI + "entity/" + (r["key"] or "").replace(" ", "_"),
            "@type": etype,
        }
        for field in ("name_ru", "name_en", "canonical", "geography"):
            if r[field]:
                node[field] = r[field]
        graph.append(node)

    rows = session.run(
        """
        MATCH (a:Entity)-[r:REL]->(b:Entity)
        RETURN a.key AS src, r.type AS type, b.key AS dst, r.evidence AS evidence
        """
    )
    for r in rows:
        rel_type = r["type"] if r["type"] in RELATION_TYPES else "related"
        graph.append({
            "@id": BASE_IRI + "entity/" + (r["src"] or "").replace(" ", "_"),
            rel_type: BASE_IRI + "entity/" + (r["dst"] or "").replace(" ", "_"),
        })

    rows = session.run(
        """
        MATCH (e:Entity)-[:HAS_CONSTRAINT]->(c:Constraint)-[:FROM_CHUNK]->(ch:Chunk)
        RETURN e.key AS entity, c.param AS param, c.op AS op,
               c.value_min AS vmin, c.value_max AS vmax, c.unit AS unit,
               c.condition AS condition, ch.doc_id AS doc_id
        LIMIT 10000
        """
    )
    for i, r in enumerate(rows):
        graph.append({
            "@id": BASE_IRI + f"constraint/{i}",
            "@type": "Constraint",
            "onEntity": BASE_IRI + "entity/" + (r["entity"] or "").replace(" ", "_"),
            "param": r["param"], "op": r["op"],
            "value_min": r["vmin"], "value_max": r["vmax"],
            "unit": r["unit"], "condition": r["condition"],
            "mentionedIn": BASE_IRI + "document/" + (r["doc_id"] or "").replace(" ", "_"),
        })

    return {"@context": CONTEXT, "@graph": graph}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="exports/knowledge_graph.jsonld")
    args = ap.parse_args()

    driver = get_driver()
    with driver.session() as session:
        doc = export(session)
    driver.close()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"[jsonld] экспортировано узлов/связей: {len(doc['@graph'])} -> {args.out}")
