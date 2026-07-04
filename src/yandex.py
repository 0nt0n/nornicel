"""Тонкая обёртка над чат-LLM. Два взаимозаменяемых бэкенда (config.LLM_BACKEND):

  yandex : Yandex AI Studio, модель gpt://<folder>/<model>/latest
  local  : любой OpenAI-совместимый сервер (Ollama/vLLM/LM Studio), одна модель

Оба говорят по OpenAI-совместимому протоколу, поэтому меняется только клиент и имя
модели — публичные функции chat_text/chat_json и их сигнатуры одинаковы. Переключение
на локальную модель и обратно — одной переменной LLM_BACKEND, без правок остального кода.
Structured output: response_format={"type":"json_schema", ...} с фолбэком на json_object.
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
        wait_time = (1.0 / _RPS_LIMIT) - (now - _last_request_time)
        if wait_time > 0:
            _last_request_time = now + wait_time
        else:
            wait_time = 0
            _last_request_time = now
    
    if wait_time > 0:
        time.sleep(wait_time)


@lru_cache(maxsize=1)
def get_yandex_client() -> OpenAI:
    """Клиент строго к Yandex. Используется эмбеддингами (YandexEmbedder)
    независимо от LLM_BACKEND — эмбеддинги переключаются своим EMBED_BACKEND."""
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


@lru_cache(maxsize=1)
def get_local_client() -> OpenAI:
    """Клиент к локальному OpenAI-совместимому серверу (Ollama/vLLM/LM Studio)."""
    return OpenAI(
        api_key=config.LOCAL_LLM_API_KEY,
        base_url=config.LOCAL_LLM_BASE_URL,
    )


def get_client() -> OpenAI:
    """Клиент для ЧАТА (извлечение/роутинг/синтез). Зависит от LLM_BACKEND."""
    if config.LLM_BACKEND == "local":
        return get_local_client()
    return get_yandex_client()


def _model_uri(model: str) -> str:
    if config.LLM_BACKEND == "local":
        return config.LOCAL_LLM_MODEL   # одна локальная модель на все роли
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
    if last is not None:
        raise last
    raise RuntimeError("API max_retries exhausted")


def chat_json(system: str, user: str, schema_name: str, schema: dict,
              model: str = None, max_retries: int = 4) -> dict:
    """Structured output по JSON-схеме. На каждой попытке сначала строгая json_schema,
    затем фолбэк на json_object (быстро подхватывается локальными моделями, которые
    json_schema могут не поддерживать)."""
    client = get_client()
    model = model or config.LLM_MODEL_MAIN
    strict_user = user
    object_user = user + "\n\nВерни ТОЛЬКО валидный JSON строго по описанной схеме, без пояснений."

    def _call(user_content, response_format):
        wait_rate_limit()
        resp = client.chat.completions.create(
            model=_model_uri(model),
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user_content}],
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
            response_format=response_format,
        )
        return resp.choices[0].message.content

    rf_schema = {"type": "json_schema",
                 "json_schema": {"name": schema_name, "schema": schema}}
    rf_object = {"type": "json_object"}
    last = None
    for attempt in range(max_retries):
        try:
            return _extract_json(_call(strict_user, rf_schema))
        except Exception as e:  # noqa: BLE001
            last = e
        try:
            return _extract_json(_call(object_user, rf_object))
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.5 * (2 ** attempt))
    if last is not None:
        raise last
    raise RuntimeError("chat_json max_retries exhausted")
