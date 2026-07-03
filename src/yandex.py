"""Тонкая обёртка над OpenAI-совместимым API Yandex AI Studio.

Studio отдаёт OpenAI-совместимый эндпоинт => используем обычную библиотеку openai.
Модель задаётся URI: gpt://<folder>/<model>/latest.
Structured output: response_format={"type":"json_schema", ...}.
Приватность: заголовок x-data-logging-enabled=false отключает логирование провайдером.
"""
import json
import time
import threading
from functools import lru_cache

from openai import OpenAI

import config

_rate_limit_lock = threading.Lock()
_last_request_time = 0.0
_RPS_LIMIT = 9.0

def wait_rate_limit():
    """Глобальный ограничитель RPS для всех запросов к Yandex API (9 RPS)."""
    global _last_request_time
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        wait_time = (1.0 / _RPS_LIMIT) - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        _last_request_time = time.time()

@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    config.require_yandex()
    return OpenAI(
        api_key=config.YANDEX_API_KEY,
        base_url=config.YANDEX_BASE_URL,
        project=config.YANDEX_FOLDER_ID,
        default_headers={
            "x-folder-id": config.YANDEX_FOLDER_ID,
            "x-data-logging-enabled": "false",  # приватность: не логировать запросы
        },
    )


def _model_uri(model: str) -> str:
    return f"gpt://{config.YANDEX_FOLDER_ID}/{model}/latest"


def _extract_json(raw: str) -> dict:
    """Достаёт JSON из ответа: снимает ```-ограждения и берёт объект между первой { и последней }."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1:
        s = s[a : b + 1]
    return json.loads(s)


def chat_text(system: str, user: str, model: str = None,
              temperature: float = None, max_retries: int = 4) -> str:
    """Обычный текстовый ответ с ретраями на сетевые/лимитные ошибки."""
    client = get_client()
    model = model or config.LLM_MODEL_MAIN
    temperature = config.LLM_TEMPERATURE if temperature is None else temperature
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    last = None
    for attempt in range(max_retries):
        try:
            wait_rate_limit()
            resp = client.chat.completions.create(
                model=_model_uri(model),
                messages=messages,
                temperature=temperature,
                max_tokens=config.MAX_TOKENS,
            )
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (2 ** attempt))
    raise last


def chat_json(system: str, user: str, schema_name: str, schema: dict,
              model: str = None, max_retries: int = 4) -> dict:
    """Structured output по JSON-схеме. Если провайдер не принял json_schema —
    откатываемся в json_object + инструкция в промпте."""
    client = get_client()
    model = model or config.LLM_MODEL_MAIN
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    def _call(response_format):
        wait_rate_limit()
        resp = client.chat.completions.create(
            model=_model_uri(model),
            messages=messages,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
            response_format=response_format,
        )
        return resp.choices[0].message.content

    rf_schema = {"type": "json_schema",
                 "json_schema": {"name": schema_name, "schema": schema}}
    last = None
    for attempt in range(max_retries):
        try:
            return _extract_json(_call(rf_schema))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (2 ** attempt))
    # запасной режим: json_object
    messages[1]["content"] += "\n\nВерни ТОЛЬКО валидный JSON строго по описанной схеме, без пояснений."
    try:
        return _extract_json(_call({"type": "json_object"}))
    except Exception:  # noqa: BLE001
        raise last
