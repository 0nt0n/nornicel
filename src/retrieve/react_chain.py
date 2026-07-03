"""ReAct-цепочка: многоуровневый обход документов (Reason + Act, 3-4 итерации).

Уровень 1 — Разведка: начальный поиск + анализ пробелов.
Уровень 2 — Углубление: дополнительные запросы по непокрытым аспектам.
Уровень 3 — Перекрёстная проверка: валидация найденных фактов, поиск противоречий.
Уровень 4 — Финальный синтез: объединение всего контекста в итоговый ответ.
"""
import json

import config
from src.yandex import chat_text
from src.embeddings import get_embedder
from src.graph import queries as Q


# --- Промпты для каждого уровня ---

REASON_L1_SYSTEM = """Ты — аналитик R&D горно-металлургической отрасли.
Тебе дан исследовательский ЗАПРОС и набор НАЙДЕННЫХ ФРАГМЕНТОВ из корпуса документов.

Задача: проанализируй, насколько полно фрагменты покрывают запрос.

Верни JSON:
{
  "covered_aspects": ["аспект 1", "аспект 2"],
  "missing_aspects": ["непокрытый аспект 1", "непокрытый аспект 2"],
  "sub_queries": ["уточняющий поисковый запрос 1", "уточняющий поисковый запрос 2"],
  "key_facts": ["ключевой факт 1 [doc_id]", "ключевой факт 2 [doc_id]"],
  "reasoning": "краткое рассуждение на 2-3 предложения"
}

Правила:
- sub_queries — это конкретные поисковые запросы для поиска НЕДОСТАЮЩЕЙ информации.
  Формулируй их как вопросы специалиста, а не общие фразы.
- Если запрос покрыт полностью — sub_queries должен быть пустым.
- key_facts — самые важные факты с числами и источниками из найденных фрагментов.
- Пиши по-русски."""

REASON_L3_SYSTEM = """Ты — аналитик R&D. Проверь найденные факты на ПРОТИВОРЕЧИЯ между источниками.

Входные данные: ЗАПРОС и ВСЕ НАЙДЕННЫЕ ФРАГМЕНТЫ (из нескольких раундов поиска).

Верни JSON:
{
  "contradictions": [
    {"fact_a": "утверждение A [doc_id]", "fact_b": "противоречащее утверждение B [doc_id]",
     "resolution_query": "запрос для разрешения противоречия"}
  ],
  "verified_facts": ["подтверждённый факт 1 [doc_id1, doc_id2]", ...],
  "confidence_assessment": "high/medium/low",
  "reasoning": "краткое рассуждение"
}

Правила:
- Если противоречий нет — список contradictions пуст.
- verified_facts — факты, подтверждённые 2+ источниками.
- Пиши по-русски."""

SYNTH_MULTI_SYSTEM = """Ты — старший аналитик R&D горно-металлургической отрасли. Составь ДЕТАЛЬНЫЙ
экспертный ответ на запрос исследователя на основе ВСЕГО собранного контекста.

Контекст содержит данные из НЕСКОЛЬКИХ раундов поиска — используй их ВСЕ.

Структура ответа:
1. **Краткий ответ** (2-3 предложения — суть).
2. **Детальный разбор** по аспектам вопроса. Каждый аспект — отдельный подраздел.
   Приводи КОНКРЕТНЫЕ числа, условия, параметры из источников.
3. **Сравнение РФ / зарубеж** (если есть данные из обоих контекстов).
4. **Противоречия и открытые вопросы** (если обнаружены в ходе анализа).
5. **Пробелы в знаниях** — чего НЕТ в корпусе и что стоит исследовать.
6. **Источники** — список использованных doc_id.
7. **Достоверность:** high/medium/low (с числом подтверждающих источников).

Правила:
- Опирайся СТРОГО на контекст. Не выдумывай.
- Числа — точно, с единицами измерения.
- Источники в квадратных скобках [doc_id].
- Пиши по-русски, деловым языком, объёмно и информативно. Минимум 300 слов.
- Если данных мало — честно скажи, но выжми максимум из того, что есть."""


def _fmt_chunks(chunks, max_chars=600):
    """Форматирует чанки для промпта."""
    parts = []
    for ch in chunks:
        conf = ch.get("confidence", "medium")
        header = f"[{ch.get('doc_id', '?')} | {ch.get('geography', '?')} | {ch.get('year', '?')} | conf={conf}]"
        text = ch.get("text", "")[:max_chars]
        parts.append(f"{header} {text}")
    return "\n\n".join(parts)


def _parse_json_safe(text):
    """Безопасный парсинг JSON из ответа LLM."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1:
        s = s[a:b + 1]
    try:
        return json.loads(s)
    except Exception:
        return {"reasoning": text, "sub_queries": [], "missing_aspects": [],
                "covered_aspects": [], "key_facts": [],
                "contradictions": [], "verified_facts": [],
                "confidence_assessment": "medium"}


def _dedup_chunks(all_chunks):
    """Дедупликация чанков по chunk_id."""
    seen = set()
    result = []
    for ch in all_chunks:
        cid = ch.get("chunk_id")
        if cid and cid not in seen:
            seen.add(cid)
            result.append(ch)
    return result


def multi_level_retrieve(session, question, slots, max_levels=4, progress_cb=None):
    """ReAct-цепочка: многоуровневый поиск с промежуточными рассуждениями.

    progress_cb: опциональный callback(level:int, message:str) — UI показывает живой
    прогресс по уровням. Логику цепочки не меняет.

    Возвращает dict с ключами:
      - all_chunks: все найденные чанки (дедуплицированные)
      - levels: список dict-ов {level, action, reasoning, chunks_found, ...}
      - constraint_hits, exp_pubs, comparison_chunks, gaps, entities, subgraph_edges
      - sources: список источников
      - slots: исходные слоты
      - final_context_text: форматированный текст для синтеза
    """
    def _notify(level, msg):
        if progress_cb:
            try:
                progress_cb(level, msg)
            except Exception:  # noqa: BLE001
                pass  # сбой UI-коллбека не должен ронять поиск

    embedder = get_embedder()
    geo = slots.get("geography") if slots.get("geography") != "unknown" else None
    year_from = slots.get("year_from")

    all_chunks = []
    levels = []

    # ===================== УРОВЕНЬ 1: Разведка =====================
    _notify(1, "Разведка: гибридный поиск (вектор + полнотекст)...")
    qvec = embedder.embed_query(question)
    # гибрид: вектор ловит смысл, Lucene-полнотекст — точные термины и аббревиатуры
    l1_chunks = Q.hybrid_search(session, qvec, question, top_k=10,
                                geography=geo, year_from=year_from)
    all_chunks.extend(l1_chunks)

    # Числовые ограничения
    constraint_hits = []
    for c in slots.get("constraints", []):
        constraint_hits += Q.find_by_constraint(
            session, param=c.get("param", ""), op=c.get("op", "eq"),
            value=c.get("value"), value_max=c.get("value_max"), geography=geo,
        )

    # Эксперименты/публикации
    exp_pubs = []
    if slots.get("intent") in ("literature_review", "list_experiments"):
        kws = slots.get("materials", []) + slots.get("processes", [])
        if kws:
            exp_pubs = Q.find_experiments_publications(
                session, keywords=kws, year_from=year_from, geography=geo
            )

    # Reason-шаг: анализ покрытия
    _notify(1, f"Разведка: найдено {len(l1_chunks)} фрагментов, анализирую покрытие запроса...")
    ctx_text = _fmt_chunks(l1_chunks)
    reason_prompt = f"ЗАПРОС:\n{question}\n\nНАЙДЕННЫЕ ФРАГМЕНТЫ:\n{ctx_text}"
    reason_response = chat_text(REASON_L1_SYSTEM, reason_prompt, model=config.LLM_MODEL_FAST)
    l1_reason = _parse_json_safe(reason_response)

    levels.append({
        "level": 1,
        "action": "Разведка — начальный поиск",
        "chunks_found": len(l1_chunks),
        "reasoning": l1_reason.get("reasoning", ""),
        "covered_aspects": l1_reason.get("covered_aspects", []),
        "missing_aspects": l1_reason.get("missing_aspects", []),
        "key_facts": l1_reason.get("key_facts", []),
        "sub_queries": l1_reason.get("sub_queries", []),
    })

    if max_levels < 2:
        all_chunks = _dedup_chunks(all_chunks)
        return _build_result(session, question, slots, all_chunks, levels,
                             constraint_hits, exp_pubs, geo, year_from, embedder, qvec)

    # ===================== УРОВЕНЬ 2: Углубление =====================
    sub_queries = l1_reason.get("sub_queries", [])[:3]  # макс. 3 подзапроса
    l2_chunks = []

    for i, sq in enumerate(sub_queries, 1):
        _notify(2, f"Углубление: подзапрос {i}/{len(sub_queries)} — «{sq[:80]}»")
        sq_vec = embedder.embed_query(sq)
        sq_chunks = Q.hybrid_search(session, sq_vec, sq, top_k=5,
                                    geography=geo, year_from=year_from)
        l2_chunks.extend(sq_chunks)

    all_chunks.extend(l2_chunks)

    levels.append({
        "level": 2,
        "action": "Углубление — дополнительные запросы",
        "sub_queries_used": sub_queries,
        "chunks_found": len(l2_chunks),
        "reasoning": f"Найдено {len(l2_chunks)} доп. фрагментов по {len(sub_queries)} подзапросам.",
    })

    if max_levels < 3:
        all_chunks = _dedup_chunks(all_chunks)
        return _build_result(session, question, slots, all_chunks, levels,
                             constraint_hits, exp_pubs, geo, year_from, embedder, qvec)

    # ===================== УРОВЕНЬ 3: Перекрёстная проверка =====================
    _notify(3, "Перекрёстная проверка фактов на противоречия между источниками...")
    all_deduped = _dedup_chunks(all_chunks)
    all_ctx = _fmt_chunks(all_deduped[:20])  # топ-20 для проверки
    verify_prompt = f"ЗАПРОС:\n{question}\n\nВСЕ НАЙДЕННЫЕ ФРАГМЕНТЫ:\n{all_ctx}"
    verify_response = chat_text(REASON_L3_SYSTEM, verify_prompt, model=config.LLM_MODEL_FAST)
    l3_reason = _parse_json_safe(verify_response)

    # Если есть противоречия — делаем ещё один поиск
    l3_extra_chunks = []
    contradictions = l3_reason.get("contradictions", [])
    for contr in contradictions[:2]:
        rq = contr.get("resolution_query", "")
        if rq:
            rq_vec = embedder.embed_query(rq)
            rq_chunks = Q.vector_search(session, rq_vec, top_k=3, geography=geo, year_from=year_from)
            l3_extra_chunks.extend(rq_chunks)

    all_chunks.extend(l3_extra_chunks)

    levels.append({
        "level": 3,
        "action": "Перекрёстная проверка",
        "contradictions_found": len(contradictions),
        "verified_facts": l3_reason.get("verified_facts", []),
        "extra_chunks": len(l3_extra_chunks),
        "confidence": l3_reason.get("confidence_assessment", "medium"),
        "reasoning": l3_reason.get("reasoning", ""),
    })

    # ===================== УРОВЕНЬ 4: Финальная сборка =====================
    _notify(4, "Финальная сборка контекста и подграфа...")
    all_chunks = _dedup_chunks(all_chunks)

    levels.append({
        "level": 4,
        "action": "Финальный синтез",
        "total_unique_chunks": len(all_chunks),
        "reasoning": f"Собрано {len(all_chunks)} уникальных фрагментов из {len(levels)} раундов поиска.",
    })

    return _build_result(session, question, slots, all_chunks, levels,
                         constraint_hits, exp_pubs, geo, year_from, embedder, qvec)


def _build_result(session, question, slots, all_chunks, levels,
                  constraint_hits, exp_pubs, geo, year_from, embedder, qvec=None):
    """Собирает финальный результат с сущностями и подграфом."""
    # Сравнительный запрос
    comparison_chunks = None
    if slots.get("comparison"):
        if qvec is None:  # вектор вопроса уже посчитан на уровне 1 — не жжём API повторно
            qvec = embedder.embed_query(question)
        comparison_chunks = {
            "RU": Q.vector_search(session, qvec, top_k=8, geography="RU", year_from=year_from),
            "foreign": Q.vector_search(session, qvec, top_k=8, geography="foreign", year_from=year_from),
        }

    # Пробелы
    gaps = Q.find_gaps(session, limit=10)

    # Сущности и подграф
    chunk_ids = [ch["chunk_id"] for ch in all_chunks if ch.get("chunk_id")]
    entities = Q.entities_for_chunks(session, chunk_ids)
    entity_keys = [e["key"] for e in entities]
    subgraph_edges = Q.neighborhood(session, entity_keys, hops=1) if entity_keys else []

    # Источники
    sources = {}
    for ch in all_chunks:
        did = ch.get("doc_id")
        if did:
            sources[did] = {"doc_id": did, "geography": ch.get("geography"),
                            "year": ch.get("year")}

    return {
        "chunks": all_chunks,
        "constraint_hits": constraint_hits,
        "exp_pubs": exp_pubs,
        "sources": list(sources.values()),
        "slots": slots,
        "comparison_chunks": comparison_chunks,
        "gaps": gaps,
        "entities": entities,
        "subgraph_edges": subgraph_edges,
        "levels": levels,
    }


def synthesize_multi(question, context, model=None):
    """Финальный синтез с многоуровневым контекстом."""
    parts = []

    # Основные чанки
    for ch in context.get("chunks", [])[:20]:
        conf = ch.get("confidence", "medium")
        parts.append(
            f"[{ch.get('doc_id', '?')} | {ch.get('geography', '?')} | "
            f"{ch.get('year', '?')} | conf={conf}] {ch.get('text', '')[:600]}"
        )

    # Сравнительные данные
    comparison = context.get("comparison_chunks")
    if comparison:
        ru_part = "\n".join(
            f"[{c.get('doc_id', '?')}] {c.get('text', '')[:400]}"
            for c in comparison.get("RU", [])[:5]
        )
        foreign_part = "\n".join(
            f"[{c.get('doc_id', '?')}] {c.get('text', '')[:400]}"
            for c in comparison.get("foreign", [])[:5]
        )
        parts.append("ОТЕЧЕСТВЕННАЯ ПРАКТИКА (RU):\n" + (ru_part or "(нет данных)"))
        parts.append("ЗАРУБЕЖНАЯ ПРАКТИКА (foreign):\n" + (foreign_part or "(нет данных)"))

    # Числовые совпадения
    if context.get("constraint_hits"):
        parts.append("ЧИСЛОВЫЕ СОВПАДЕНИЯ: " +
                      json.dumps(context["constraint_hits"][:10], ensure_ascii=False)[:1500])
    if context.get("exp_pubs"):
        parts.append("ЭКСПЕРИМЕНТЫ/ПУБЛИКАЦИИ: " +
                      json.dumps(context["exp_pubs"][:10], ensure_ascii=False)[:1500])
    if context.get("gaps"):
        parts.append("ПРОБЕЛЫ: " +
                      json.dumps(context["gaps"][:10], ensure_ascii=False)[:1000])

    # Цепочка рассуждений
    reasoning_chain = []
    for lvl in context.get("levels", []):
        reasoning_chain.append(
            f"[Уровень {lvl['level']}: {lvl['action']}] {lvl.get('reasoning', '')}"
        )
    if reasoning_chain:
        parts.append("ЦЕПОЧКА РАССУЖДЕНИЙ:\n" + "\n".join(reasoning_chain))

    ctx = "\n\n".join(parts) if parts else "(контекст пуст)"
    user = f"ЗАПРОС:\n{question}\n\nКОНТЕКСТ:\n{ctx}"
    return chat_text(SYNTH_MULTI_SYSTEM, user, model=model or config.LLM_MODEL_MAIN)
