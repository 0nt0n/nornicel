"""Единая конфигурация. Всё читается из .env (см. .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Yandex AI Studio (OpenAI-совместимый API) ---
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
# Официальный эндпоинт structured output. Альтернатива: https://llm.api.cloud.yandex.net/v1
YANDEX_BASE_URL = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1")

# Модели. URI собирается как gpt://<folder>/<model>/latest
LLM_MODEL_MAIN = os.getenv("LLM_MODEL_MAIN", "yandexgpt")        # Pro — для извлечения и синтеза
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "yandexgpt-lite")   # Lite — для роутинга/массового прогона
# Тяжёлая артиллерия на спорные чанки (доступна в Studio): "qwen3-235b-a22b-fp8", "deepseek-*"
LLM_MODEL_HEAVY = os.getenv("LLM_MODEL_HEAVY", "yandexgpt")

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))

# --- Бэкенд чат-LLM: yandex (облако) | local (OpenAI-совместимый сервер) ---
# Когда Yandex API недоступен, извлечение/роутинг/синтез уходят на локальную модель
# (Ollama/vLLM/LM Studio — все они говорят по OpenAI-совместимому протоколу).
# Формат чекпоинтов извлечения одинаков для обоих бэкендов — возврат к Yandex не требует
# миграции данных, достаточно поменять LLM_BACKEND обратно. Эмбеддинги переключаются
# ОТДЕЛЬНО через EMBED_BACKEND (см. ниже) и не зависят от LLM_BACKEND.
LLM_BACKEND = os.getenv("LLM_BACKEND", "yandex")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# Ollama ключ не проверяет, но клиент openai требует непустую строку
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
# Одна локальная модель на всё (извлечение + роутинг + синтез). Для Ollama — тег модели.
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# --- Эмбеддинги ---
# EMBED_BACKEND: "yandex" (emb://<folder>/text-search-*) или "e5" (локальный multilingual-e5, офлайн/бесплатно)
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "yandex")
EMBED_MODEL_DOC = os.getenv("EMBED_MODEL_DOC", "text-search-doc")
EMBED_MODEL_QUERY = os.getenv("EMBED_MODEL_QUERY", "text-search-query")
E5_MODEL = os.getenv("E5_MODEL", "intfloat/multilingual-e5-base")

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
VECTOR_INDEX = "chunk_embeddings"
FULLTEXT_INDEX = "chunk_fulltext"

# --- Пайплайн ---
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))     # символов
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
# Чанки короче этого — обрывки без смысловой нагрузки (номера страниц, колонтитулы):
# в граф не идут, LLM-вызовы на них не тратятся.
MIN_CHUNK_CHARS = int(os.getenv("MIN_CHUNK_CHARS", "80"))
RAW_DIR = os.getenv("RAW_DIR", "data/raw")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "data/processed")

# Конкурентные запросы к Yandex API (извлечение и эмбеддинги).
# По умолчанию 1 (последовательно) — Yandex AI Studio плохо переносит конкурентные
# запросы с одного ключа: начинает тротлить, ретраи с бэкоффом стакаются и всё
# становится МЕДЛЕННЕЕ, чем последовательно. Поднимайте осторожно и проверяйте на практике.
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))


def require_yandex():
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise RuntimeError(
            "Не заданы YANDEX_API_KEY / YANDEX_FOLDER_ID. Скопируй .env.example в .env и заполни."
        )
