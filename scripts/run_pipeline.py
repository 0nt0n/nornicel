"""Полный офлайн-прогон корпуса: парсинг -> извлечение (с чекпоинтами) -> загрузка в граф.

Запуск:
    python scripts/run_pipeline.py                          # весь корпус из data/raw
    python scripts/run_pipeline.py --limit 1                # вертикальный срез: 1 документ
    python scripts/run_pipeline.py --subdir "Журналы/Цветные металлы/2020"  # только подпапка
    python scripts/run_pipeline.py --force                  # не пропускать уже обработанные файлы
    python scripts/run_pipeline.py --load-only               # только загрузить уже извлечённое в граф
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.ingest.parse import parse_dir
from src.extract.extract import extract_document
from src.embeddings import get_embedder
from src.graph.loader import get_driver, load_processed
from src.graph.indexes import init_schema


def run_extract(limit=None, subdir=None, force=False):
    chunks = parse_dir(config.RAW_DIR, subdir=subdir, skip_processed=not force)
    by_doc = defaultdict(list)
    for ch in chunks:
        by_doc[ch.doc_id].append(ch)
    docs = list(by_doc.items())
    if limit:
        docs = docs[:limit]
    print(f"[pipeline] документов: {len(docs)}, чанков: {sum(len(v) for _, v in docs)}")
    for doc_id, doc_chunks in docs:
        print(f"[extract] {doc_id} ({len(doc_chunks)} чанков)...")
        extract_document(doc_id, doc_chunks, model=config.LLM_MODEL_MAIN, resume=True)
    print("[extract] готово, результаты в", config.PROCESSED_DIR)


def run_load():
    embedder = get_embedder()
    dim = embedder.dim()
    print(f"[load] эмбеддер={config.EMBED_BACKEND}, dim={dim}")
    driver = get_driver()
    with driver.session() as session:
        init_schema(session, dim)
        for path in glob.glob(os.path.join(config.PROCESSED_DIR, "*.json")):
            with open(path, encoding="utf-8") as f:
                processed = json.load(f)
            print(f"[load] {os.path.basename(path)}: {len(processed)} чанков")
            load_processed(session, processed, embedder)
    driver.close()
    print("[load] граф собран. Открой Neo4j Browser: http://localhost:7474")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--subdir", type=str, default=None,
                     help="ограничиться подпапкой внутри data/raw, напр. 'Журналы/Цветные металлы/2020'")
    ap.add_argument("--force", action="store_true",
                     help="не пропускать файлы, для которых уже есть чекпоинт в data/processed")
    ap.add_argument("--load-only", action="store_true")
    ap.add_argument("--extract-only", action="store_true")
    args = ap.parse_args()

    if not args.load_only:
        run_extract(limit=args.limit, subdir=args.subdir, force=args.force)
    if not args.extract_only:
        run_load()
