"""Загрузка фикстуры в Neo4j (шаг 4а)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph.loader import get_driver, load_processed
from src.graph.indexes import init_schema
from src.embeddings import get_embedder

print("[4а] Подключаюсь к Yandex эмбеддеру...")
embedder = get_embedder()
dim = embedder.dim()
print(f"[4а] Размерность эмбеддингов: {dim}")

print("[4а] Подключаюсь к Neo4j...")
driver = get_driver()
with driver.session() as session:
    print("[4а] Создаю схему (индексы, constraints)...")
    init_schema(session, dim)

    print("[4а] Загружаю фикстуру...")
    with open("fixtures/sample_extraction.json", encoding="utf-8") as f:
        processed = json.load(f)
    load_processed(session, processed, embedder)

driver.close()
print("[4а] Fixture loaded! Открой Neo4j Browser: http://localhost:7474")
