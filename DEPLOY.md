# Развёртывание на удалённом сервере

Идея: **extraction (дорогие LLM-вызовы) гоняется локально у команды**, на сервер
заливаются только готовые `data/processed/*.json`. Сервер строит из них граф + векторную
БД (Neo4j) и раздаёт UI. Сырые 4.9 ГБ документов на сервер не нужны.

## Требования к серверу

- Docker + docker compose plugin (`docker compose version` должен работать)
- ~4 ГБ RAM (2G heap + 1G pagecache для Neo4j + приложение)
- Открытый порт 8501 (UI); Neo4j наружу не торчит (привязан к 127.0.0.1)

## Первый запуск

```bash
# 1. Код на сервер (или git clone)
git clone <repo-url> nornicel && cd nornicel

# 2. Ключи
cp .env.example .env
nano .env          # YANDEX_API_KEY, YANDEX_FOLDER_ID — нужны серверу:
                   # эмбеддинги при загрузке + роутер/синтез при ответах на вопросы

# 3. Залить обработанные JSON с локальной машины (запускается ЛОКАЛЬНО)
rsync -av --progress data/processed/ user@server:~/nornicel/data/processed/

# 4. Поднять контур
docker compose -f docker-compose.prod.yml up -d --build

# 5. Построить граф + векторный индекс из JSON (без LLM-извлечения)
docker compose -f docker-compose.prod.yml run --rm app \
    python scripts/run_pipeline.py --load-only

# 6. Открыть UI
# http://<server-ip>:8501
```

## Долить новые документы

Extraction — локально, потом:

```bash
rsync -av --progress data/processed/ user@server:~/nornicel/data/processed/
docker compose -f docker-compose.prod.yml run --rm app \
    python scripts/run_pipeline.py --load-only
```

Загрузка идемпотентна (`MERGE` по `chunk_id`/`key`) — дублей не будет.
Учтите: `--load-only` заново эмбеддит все JSON в `data/processed/` — при больших
объёмах это время и API-вызовы (эмбеддинги, не LLM).

## Отладка

```bash
docker compose -f docker-compose.prod.yml logs -f app     # логи приложения
docker compose -f docker-compose.prod.yml logs neo4j       # логи Neo4j

# Neo4j Browser с локальной машины через SSH-туннель:
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 user@server
# затем открыть http://localhost:7474 (neo4j / пароль из .env)
```

## Безопасность

- `.env` не попадает ни в git (`.gitignore`), ни в образ (`.dockerignore`) —
  ключи живут только в файле на сервере.
- Neo4j Bolt/HTTP привязаны к 127.0.0.1 — доступ только через SSH-туннель.
- Смените `NEO4J_PASSWORD` в `.env` на сервере (compose подхватит его и для
  контейнера Neo4j, и для приложения).
- UI на 8501 открыт всем — если нужен ограниченный доступ, закройте порт
  файрволом и ходите через SSH-туннель, либо поставьте reverse-proxy с auth.
