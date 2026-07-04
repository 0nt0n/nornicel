# Локальный запуск без Yandex API

Когда доступ к Yandex AI Studio закрыт, извлечение (и весь пайплайн) можно гонять на
**локальной модели Qwen** через Ollama. Формат чекпоинтов `data/processed/*.json`
одинаков для обоих бэкендов — вернуться на Yandex позже можно одной переменной
`LLM_BACKEND`, без миграции данных.

Два сценария (можно совмещать, деля корпус по подпапкам через `--subdir`):

| Где | Скорость | Когда |
|---|---|---|
| **Colab (T4 GPU)** | быстро (10–50× CPU) | массовая обработка → `notebooks/colab_extract.ipynb` |
| **Второй ноут (CPU)** | медленно, но офлайн | всегда под рукой, без интернета → эта инструкция |

---

## Модель

**Qwen2.5-7B-Instruct** (Q4_K_M, ~4.7 ГБ) — сильный русский + английский, хорошо
держит структурированный JSON-вывод, помещается в 12 ГБ RAM. Если на CPU слишком
медленно — возьми `qwen2.5:3b-instruct` (~2 ГБ, `LOCAL_LLM_MODEL=qwen2.5:3b-instruct`).

---

## Запуск на втором ноутбуке (~12 ГБ RAM)

```bash
# 1. Ollama (движок локальной LLM, не pip-пакет)
#    macOS:  https://ollama.com/download  (или: brew install ollama)
#    Linux:  curl -fsSL https://ollama.com/install.sh | sh
ollama serve            # держать в отдельном терминале

# 2. Модель + увеличенный контекст (num_ctx обязателен, см. ниже)
ollama pull qwen2.5:7b-instruct
ollama create minekg-qwen -f ollama/Modelfile.qwen

# 3. Проект
git clone --branch feature/local_llm <repo-url> nornicel && cd nornicel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-local.txt   # +sentence-transformers для e5

# 4. Конфиг: локальный бэкенд
cp .env.example .env
# в .env выставить:
#   LLM_BACKEND=local
#   LOCAL_LLM_MODEL=minekg-qwen
#   EMBED_BACKEND=e5        # локальные эмбеддинги, тоже без Yandex

# 5. Документы в data/raw/, затем извлечение
python scripts/run_pipeline.py --extract-only                 # весь корпус
python scripts/run_pipeline.py --extract-only --subdir "Статьи"   # или подпапка
```

Результат — `data/processed/*.json`. Уже обработанные файлы пропускаются (чекпоинты),
прогон можно прерывать и продолжать.

### Построить граф локально (тоже без Yandex)

```bash
python scripts/run_pipeline.py --load-only     # эмбеддинги e5 + запись в Neo4j
```

> ⚠️ Смена `EMBED_BACKEND` меняет размерность вектора (yandex=256 ↔ e5=768).
> Нельзя долить e5-векторы в граф, построенный на Yandex-эмбеддингах — векторный
> индекс создаётся под одну размерность. Для смены бэкенда эмбеддингов граф пересобирается
> с нуля (`docker compose down -v` → `up -d` → `--load-only`).

---

## Почему нужен `ollama/Modelfile.qwen`

У Ollama по умолчанию маленькое окно контекста (`num_ctx` 2048/4096). Наш промпт
извлечения (системная инструкция + чанк + до 4000 токенов JSON на выходе) в него не
влезает — модель молча обрежет вход и вернёт пустой/битый результат. Modelfile
поднимает `num_ctx` до 8192. Поэтому используем `minekg-qwen`, а не сырой
`qwen2.5:7b-instruct`.

---

## Возврат на Yandex

Когда доступ восстановится — в `.env`:

```
LLM_BACKEND=yandex
EMBED_BACKEND=yandex
```

Всё, что уже извлечено локально, останется валидным: `--load-only` построит граф из
тех же JSON. Повторное извлечение не требуется.

---

## Как это устроено в коде

- `config.LLM_BACKEND` (`yandex`|`local`) переключает только клиента и имя модели в
  [src/yandex.py](src/yandex.py). Публичные `chat_text`/`chat_json` и их сигнатуры не
  меняются — остальной код (роутер, извлечение, синтез) не знает, какой бэкенд активен.
- Эмбеддинги переключаются **отдельно** через `EMBED_BACKEND` и используют выделенный
  `get_yandex_client()` — не зависят от `LLM_BACKEND`.
- Локальная модель и Yandex обе говорят по OpenAI-совместимому протоколу, поэтому
  библиотека `openai` и вся логика запросов переиспользуются как есть.
