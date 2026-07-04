# Карта знаний R&D — горно-металлургия

GraphRAG-система для НИОКР горно-металлургии. Разнородные документы (PDF / PPTX / DOCX,
русский + английский) превращаются в граф знаний Neo4j с векторным и полнотекстовым
индексом, а поверх него работает многоуровневая ReAct-цепочка рассуждений, которая
отвечает на вопросы на естественном языке — с источниками, числовыми ограничениями и
уровнем достоверности.

Движок — **Yandex AI Studio** (OpenAI-совместимый API: chat, structured output, эмбеддинги).
Весь контур поднимается локально в Docker.

---

## Как это устроено

```
data/raw/*.pdf,pptx,docx
   │  src/ingest/parse.py        парсинг + чанкинг + определение языка/года
   ▼
чанки
   │  src/extract/extract.py     Yandex structured output → JSON по онтологии-контракту
   ▼                             (чекпоинт после каждого чанка)
data/processed/*.json
   │  src/graph/loader.py        дедуп сущностей, связи, ограничения, эмбеддинги
   ▼
Neo4j  (граф + vector index + fulltext index)
   │  src/retrieve/router.py       запрос → слоты (интент, числовые/гео/врем. фильтры)
   │  src/retrieve/react_chain.py  4 уровня: разведка → углубление → кросс-проверка → синтез
   │  src/retrieve/synthesize.py   подграф + источники → ответ с цитатами и достоверностью
   ▼
Streamlit UI / CLI
```

**Онтология-контракт** (`schema/ontology.py`) — единая форма извлечения. Сущности:
Material, Process, Equipment, Property, Experiment, Publication, Expert, Facility,
Conclusion, Recommendation. Связи: uses_material, operates_at_condition, produces_output,
described_in, validated_by, contradicts, expert_in.

**Ретрив без риска:** LLM не пишет Cypher. Роутер извлекает параметры, которые
подставляются в написанные вручную шаблоны запросов (`src/graph/queries.py`). Новый тип
вопроса = новый шаблон.

**Соответствие рекомендациям организаторов:**

| Рекомендация | Решение |
|---|---|
| Графовые БД (Neo4j / Neptune / JanusGraph) | Neo4j 5.26 — граф, vector index и Lucene fulltext в одной БД |
| Поиск (Elasticsearch / Vespa) | Lucene fulltext внутри Neo4j + гибридный ретрив (RRF-слияние с вектором) |
| NLP (DeepPavlov / spaCy / ruBERT) | LLM structured output (YandexGPT) + langdetect — извлекаются сущности, связи и числовые ограничения из двуязычного корпуса |
| Онтологии (OWL / RDF / SHACL) | онтология-контракт в коде + экспорт в JSON-LD (`scripts/export_jsonld.py`) |

Подробнее — `SOLUTION_ARCHITECTURE_AND_TECH_STACK.md`.

---

## Быстрый старт (локально)

```bash
# 1. Окружение
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Neo4j (только база)
docker compose up -d          # Neo4j Browser: http://localhost:7474 (neo4j / password123)

# 3. Ключи
cp .env.example .env          # заполнить YANDEX_API_KEY и YANDEX_FOLDER_ID

# 4. Загрузить готовый граф из закоммиченных data/processed/*.json
python scripts/run_pipeline.py --load-only

# 5. Спросить
python scripts/ask.py "Какие методы обессоливания при сульфатах 200-300 мг/л и сухом остатке <=1000?"
streamlit run src/app/streamlit_app.py        # веб-интерфейс: http://localhost:8501
```

Проверить связку граф + ретрив + синтез на одном чанке, без реального извлечения:

```bash
python scripts/load_fixture.py                # грузит fixtures/sample_extraction.json
```

---

## Обработка корпуса

В репозитории уже лежат предобработанные JSON (`data/processed/`), поэтому граф строится
без обращения к LLM. Чтобы обработать свои документы, положите их в `data/raw/` и запустите
пайплайн:

```bash
python scripts/run_pipeline.py --limit 1                    # 1 документ end-to-end (проверка)
python scripts/run_pipeline.py --subdir "Доклады"           # конкретная подпапка
python scripts/run_pipeline.py                              # весь корпус
python scripts/run_pipeline.py --subdir "Доклады" --force   # перепарсить, игнорируя чекпоинты
python scripts/run_pipeline.py --extract-only               # только извлечь в data/processed
python scripts/run_pipeline.py --load-only                  # только загрузить JSON в граф
```

- Извлечение чекпоинтит после каждого чанка — обрыв не теряет прогон, повторный запуск
  пропускает уже обработанные файлы.
- Загрузка идемпотентна (`MERGE` по `chunk_id` / `key`, уже загруженные чанки пропускаются) —
  дублей и лишних пересчётов эмбеддингов не будет.
- Год и география документа определяются из структуры пути и метаданных файла, а не
  гадаются LLM по каждому чанку — единое значение на документ.
- Поддерживаются PDF / PPTX / DOCX (+ `.zip` разворачивается). `.rar` / `.xls` / `.xlsx` /
  старый бинарный `.doc` пропускаются, список — в лог.

---

## Развёртывание

### Публичная демо-ссылка (ngrok)

Neo4j и приложение крутятся в Docker, наружу отдаёт ngrok по статическому домену. Нужен
бесплатный токен ngrok и, для фиксированного адреса, зарезервированный домен.

```bash
# в .env: YANDEX_API_KEY, YANDEX_FOLDER_ID, NGROK_AUTHTOKEN
# в docker-compose.tunnel.yml подставьте свой --domain (или уберите его для случайного адреса)
docker compose -f docker-compose.tunnel.yml up -d --build
```

При старте приложение строит граф из закоммиченных `data/processed/*.json` (идемпотентно)
и поднимает Streamlit. Локально доступно на http://localhost:8501, публично — по домену ngrok.

Extraction (дорогие LLM-вызовы) гоняется где угодно — на демо-хост нужны только готовые
`data/processed/*.json`, сырые документы там не требуются.

### Долить новые документы

```bash
python scripts/run_pipeline.py --extract-only --subdir "Статьи"   # обработать локально
git add data/processed && git commit                              # (по желанию)
docker compose -f docker-compose.tunnel.yml restart app           # подхватить новые JSON
```

Контейнер грузит только готовые JSON; сырые файлы из `data/raw/` он сам не извлекает.

---

## Структура репозитория

| Путь | Назначение |
|---|---|
| `schema/ontology.py` | онтология-контракт: сущности, связи, ограничения + JSON-схемы |
| `src/ingest/parse.py` | PDF / PPTX / DOCX → чанки |
| `src/extract/` | извлечение через Yandex + промпты + чекпоинты |
| `src/yandex.py` | клиент Yandex (chat, structured output, ретраи, rate limit) |
| `src/embeddings.py` | эмбеддинги: Yandex или локальный e5 |
| `src/graph/` | загрузчик, индексы, Cypher-шаблоны |
| `src/retrieve/` | роутер, ReAct-цепочка, синтез |
| `src/app/streamlit_app.py` | веб-интерфейс: поиск, цепочка рассуждений, подграф, аналитика, экспорт |
| `scripts/run_pipeline.py` | офлайн-прогон корпуса (extract / load) |
| `scripts/ask.py` | вопрос из терминала |
| `scripts/load_fixture.py` | загрузка тест-фикстуры в граф |
| `scripts/export_jsonld.py` | экспорт графа в JSON-LD (RDF-совместимо, FAIR) |
| `config.py` | вся конфигурация, читается из `.env` |
| `docker-compose.yml` | только Neo4j (локальная разработка) |
| `docker-compose.tunnel.yml` | Neo4j + приложение + ngrok (публичная демо) |

---

## Настройки (`.env`)

Все параметры — в `config.py`, значения по умолчанию рабочие. Ключевое:

- **Ключи Yandex:** `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` (обязательны — эмбеддинги при
  загрузке, роутинг и синтез при ответах).
- **Модели:** `LLM_MODEL_MAIN=yandexgpt` (извлечение / синтез), `LLM_MODEL_FAST=yandexgpt-lite`
  (роутинг). В Studio доступны и тяжёлые модели (`qwen3-235b-a22b-fp8` и др.) для спорных чанков.
- **Эмбеддинги:** `EMBED_BACKEND=yandex` (в контуре) или `e5` (локально, офлайн —
  `pip install sentence-transformers`).
- **Neo4j:** `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`. Внутри Docker-сети URI
  перекрывается на `bolt://neo4j:7687`.
- **Конкурентность:** `MAX_WORKERS=1` — Yandex AI Studio плохо переносит конкурентные
  запросы с одного ключа (тротлинг, ретраи стакаются). Поднимать осторожно.
- **ngrok:** `NGROK_AUTHTOKEN` — для публичной демо-ссылки.

`.env` и `data/` — в `.gitignore`; ключи в репозиторий не попадают (и в образ тоже — см. `.dockerignore`).

---

## Ссылки

- Yandex AI Studio — https://ai.api.cloud.yandex.net/v1
- Neo4j vector index — https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
