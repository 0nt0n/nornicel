"""Единая конфигурация. Всё читается из .env (см. .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_BASE_URL = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1")

LLM_MODEL_MAIN = os.getenv("LLM_MODEL_MAIN", "yandexgpt")
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "yandexgpt-lite")
LLM_MODEL_HEAVY = os.getenv("LLM_MODEL_HEAVY", "yandexgpt")

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))

EMBED_BACKEND = os.getenv("EMBED_BACKEND", "yandex")
EMBED_MODEL_DOC = os.getenv("EMBED_MODEL_DOC", "text-search-doc")
EMBED_MODEL_QUERY = os.getenv("EMBED_MODEL_QUERY", "text-search-query")
E5_MODEL = os.getenv("E5_MODEL", "intfloat/multilingual-e5-base")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
VECTOR_INDEX = "chunk_embeddings"
FULLTEXT_INDEX = "chunk_fulltext"

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
MIN_CHUNK_CHARS = int(os.getenv("MIN_CHUNK_CHARS", "80"))
RAW_DIR = os.getenv("RAW_DIR", "data/raw")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "data/processed")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))

def require_yandex():
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise RuntimeError(
            "Не заданы YANDEX_API_KEY / YANDEX_FOLDER_ID. Скопируй .env.example в .env и заполни."
        )
