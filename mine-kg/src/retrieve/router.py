"""NL-запрос -> структурные слоты (интент + фильтры). LLM разбирает запрос, не ходит в граф."""
import config
from schema.ontology import QUERY_SLOTS_JSON_SCHEMA
from src.yandex import chat_json

ROUTER_SYSTEM = """Ты разбираешь запрос исследователя горно-металлургической тематики
в структурные слоты для поиска по графу знаний. Верни ТОЛЬКО JSON по схеме.

- intent: literature_review | find_solutions | compare | list_experiments | other
- materials / processes: ключевые сущности из запроса (можно RU или EN).
- constraints: числовые ограничения. "сульфаты <200 мг/л" -> {param:"sulfates", op:"le", value_max:200, unit:"mg/l"}.
  "200–300 мг/л" -> {param:..., op:"range", value:200, value_max:300, unit:"mg/l"}.
- geography: RU если явно про отечественную практику, foreign если про зарубежную, иначе unknown.
- year_from/year_to: если есть временной диапазон ("за последние 5 лет" -> year_from = текущий_год-5).
- comparison: true если это сравнительный запрос (вариант А vs Б, РФ vs мир)."""


def route(question: str, model: str = None) -> dict:
    slots = chat_json(
        system=ROUTER_SYSTEM,
        user=f"Запрос: {question}",
        schema_name="query_slots",
        schema=QUERY_SLOTS_JSON_SCHEMA,
        model=model or config.LLM_MODEL_FAST,   # роутинг дешёвой моделью
    )
    slots.setdefault("materials", [])
    slots.setdefault("processes", [])
    slots.setdefault("constraints", [])
    slots.setdefault("geography", "unknown")
    return slots
