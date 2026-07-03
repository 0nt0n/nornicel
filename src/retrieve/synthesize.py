"""Синтез ответа: контекст (чанки + числовые совпадения + источники) -> ответ на естественном языке
с цитированием источников, разделением РФ/зарубеж, уровнем достоверности и указанием пробелов.
"""
import json

import config
from src.yandex import chat_text

SYNTH_SYSTEM = """Ты — аналитик R&D горно-металлургической отрасли. На основе ПРЕДОСТАВЛЕННОГО контекста
(и только его) дай структурированный ответ на запрос исследователя.

Требования:
- Опирайся строго на контекст. Если данных не хватает — прямо скажи, чего не хватает (пробел в знаниях).
- Числа приводи точно, с единицами. Не выдумывай значения, которых нет в контексте.
- Указывай источники по doc_id в квадратных скобках, напр. [report_12].
- Если в контексте есть и отечественная (RU), и зарубежная (foreign) практика — раздели их.
- В конце добавь строку "Достоверность: high/medium/low" с числом подтверждающих источников.
- Пиши по-русски, деловым языком, без воды."""


def _compact(context: dict, max_chunks: int = 10) -> str:
    parts = []
    for ch in context.get("chunks", [])[:max_chunks]:
        parts.append(f"[{ch['doc_id']} | {ch.get('geography')} | {ch.get('year')}] {ch['text'][:600]}")
    if context.get("constraint_hits"):
        parts.append("ЧИСЛОВЫЕ СОВПАДЕНИЯ: " +
                     json.dumps(context["constraint_hits"][:10], ensure_ascii=False)[:1500])
    if context.get("exp_pubs"):
        parts.append("ЭКСПЕРИМЕНТЫ/ПУБЛИКАЦИИ: " +
                     json.dumps(context["exp_pubs"][:10], ensure_ascii=False)[:1500])
    return "\n\n".join(parts) if parts else "(контекст пуст)"


def synthesize(question: str, context: dict, model: str = None) -> str:
    ctx = _compact(context)
    user = f"ЗАПРОС:\n{question}\n\nКОНТЕКСТ:\n{ctx}"
    return chat_text(SYNTH_SYSTEM, user, model=model or config.LLM_MODEL_MAIN)
