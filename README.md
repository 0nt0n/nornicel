# Карта знаний R&D — Норникель AI Science Hack

GraphRAG-система для горно-металлургии: разнородные документы (PDF/PPTX/DOCX, RU+EN) →
извлечение сущностей/связей/**числовых ограничений** → граф знаний Neo4j (+ векторный индекс) →
ответы на естественном языке с источниками и уровнем достоверности.

Движок — **Yandex AI Studio** (OpenAI-совместимый API, structured output, эмбеддинги). Всё в контуре заказчика.

---

## Быстрый старт (вертикальный срез — сначала это)

```bash
# 1. Зависимости
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Neo4j
docker compose up -d           # Neo4j Browser: http://localhost:7474 (neo4j / password123)

# 3. Ключи
cp .env.example .env           # заполни YANDEX_API_KEY и YANDEX_FOLDER_ID

# 4а. Проверка графа БЕЗ извлечения — грузим готовую фикстуру
python -c "import json,sys; sys.path.insert(0,'.'); \
from src.graph.loader import get_driver, load_processed; \
from src.graph.indexes import init_schema; from src.embeddings import get_embedder; \
e=get_embedder(); d=get_driver(); s=d.session(); init_schema(s,e.dim()); \
load_processed(s, json.load(open('fixtures/sample_extraction.json')), e); print('fixture loaded')"

# 4б. Полный прогон корпуса (положи файлы в data/raw/)
python scripts/run_pipeline.py --limit 1                              # 1 документ end-to-end
python scripts/run_pipeline.py --subdir "Доклады"                     # конкретная подпапка
python scripts/run_pipeline.py                                        # весь корпус
python scripts/run_pipeline.py --subdir "Доклады" --force             # перепарсить, игнорируя чекпоинты

# 5. Спросить
python scripts/ask.py "Какие методы обессоливания при сульфатах 200-300 мг/л и сухом остатке <=1000?"
streamlit run src/app/streamlit_app.py       # UI
```

> **Порядок работы (из гайда):** сначала прогони фикстуру (4а) и убедись, что граф + ретрив + синтез
> работают на одном чанке. Только потом включай реальное извлечение (4б). Вертикальный срез раньше ширины.

---

## Архитектура

```
data/raw/*.pdf,pptx,docx
   │  src/ingest/parse.py            парсинг + чанкинг + язык
   ▼
чанки
   │  src/extract/extract.py         Yandex structured output → JSON по контракту (чекпоинты!)
   ▼
data/processed/*.json
   │  src/graph/loader.py            дедуп сущностей, связи, ограничения, эмбеддинги
   ▼
Neo4j (граф + vector index)
   │  src/retrieve/router.py         NL-запрос → слоты (интент + числовые/гео/врем. фильтры)
   │  src/retrieve/retriever.py      вектор находит старт → Cypher-шаблоны обходят граф
   │  src/retrieve/synthesize.py     подграф + источники → ответ с цитатами и достоверностью
   ▼
Streamlit / CLI
```

**Контракт** (`schema/ontology.py`) — единая форма извлечения. Меняется только по согласованию команды.
Сущности: Material, Process, Equipment, Property, Experiment, Publication, Expert, Facility,
Conclusion, Recommendation. Связи: uses_material, operates_at_condition, produces_output,
described_in, validated_by, contradicts, expert_in.

**Ретрив без риска:** LLM НЕ пишет Cypher. Он подставляет параметры в руками написанные шаблоны
(`src/graph/queries.py`). Хотите новый тип вопроса — добавьте туда шаблон.

---

## Структура

| Путь | Назначение | Ответственный |
|---|---|---|
| `schema/ontology.py` | ⭐ контракт: сущности/связи/ограничения + JSON-схемы | все (по согласованию) |
| `src/ingest/parse.py` | PDF/PPTX/DOCX → чанки | A |
| `src/extract/` | извлечение через Yandex + промпты + чекпоинты | A, B |
| `src/yandex.py` | клиент Yandex (chat + structured output + ретраи) | B |
| `src/embeddings.py` | эмбеддинги: yandex или локальный e5 | B |
| `src/graph/` | загрузчик, индексы, Cypher-шаблоны | C |
| `src/retrieve/` | роутер, ретривер, синтез | D |
| `src/app/streamlit_app.py` | интерфейс: поиск, подграф сущностей, сравнение РФ/зарубеж, дашборд, экспорт | E |
| `scripts/run_pipeline.py` | офлайн-прогон корпуса | C |
| `scripts/ask.py` | вопрос из терминала | D |

---

## Настройки (`.env`)

- **Модели:** `LLM_MODEL_MAIN=yandexgpt` (Pro) для извлечения/синтеза, `LLM_MODEL_FAST=yandexgpt-lite` для роутинга.
  Тяжёлые чанки с числами можно гнать через `qwen3-235b-a22b-fp8` (доступна в Studio) — поставь в `LLM_MODEL_MAIN`.
- **Эмбеддинги:** `EMBED_BACKEND=yandex` (в контуре) или `e5` (локально, офлайн — тогда `pip install sentence-transformers`).
- **Приватность:** клиент шлёт заголовок `x-data-logging-enabled: false` — провайдер не логирует запросы (аргумент для питча по ИБ).

## Заметки

- Векторный индекс создаётся под размерность эмбеддера автоматически (`init_schema`).
- Извлечение чекпоинтит после **каждого** чанка в `data/processed/` — обрыв не теряет прогон.
- `parse_dir()` пропускает файлы, для которых уже есть чекпоинт (`--force` — принудительный перепарсинг),
  и разворачивает `.zip` перед парсингом. `.rar`/`.xls`/`.xlsx`/старый бинарный `.doc` — не поддерживаются,
  список пропущенных типов печатается в лог.
- Год/география документа определяются в первую очередь из структуры пути (`Журналы/.../2020/`,
  `ОИП-03-2022...`), а не гадаются LLM независимо по каждому чанку — единое значение на весь документ
  (`src/extract/extract.py::_finalize_metadata`).
- `MAX_WORKERS` (по умолчанию 1) — Yandex AI Studio плохо переносит конкурентные запросы с одного ключа,
  поднимайте только после проверки на практике.
- `data/` и `.env` — в `.gitignore`. Ключ в репозиторий не коммитить; при утечке — перевыпустить в AI Studio.
- Опциональный апгрейд: официальный пакет `neo4j-graphrag-python` (готовые `VectorCypherRetriever`).

## Полезные ссылки

- Yandex AI Studio structured output: https://ai.api.cloud.yandex.net/v1 (см. доки AI Studio)
- Neo4j vector index: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- neo4j-graphrag-python: https://neo4j.com/docs/neo4j-graphrag-python/current/
