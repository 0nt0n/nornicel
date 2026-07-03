"""Задать вопрос системе из терминала (быстрый тест без UI).

Запуск:
    python scripts/ask.py "Какие методы обессоливания воды при сульфатах 200-300 мг/л и сухом остатке <=1000?"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph.loader import get_driver
from src.retrieve.router import route
from src.retrieve.retriever import retrieve
from src.retrieve.synthesize import synthesize


def answer(question: str) -> str:
    slots = route(question)
    driver = get_driver()
    with driver.session() as session:
        context = retrieve(session, question, slots)
    driver.close()
    return synthesize(question, context), slots, context


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Какие методы обессоливания воды описаны в корпусе?"
    ans, slots, ctx = answer(q)
    print("\n=== СЛОТЫ ===")
    print(slots)
    print(f"\n=== ИСТОЧНИКИ ({len(ctx['sources'])}) ===")
    print(ctx["sources"])
    print("\n=== ОТВЕТ ===")
    print(ans)
