"""Streamlit-интерфейс: запрос на естественном языке -> ответ + источники + подграф.

Запуск:
    streamlit run src/app/streamlit_app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from src.graph.loader import get_driver
from src.retrieve.router import route
from src.retrieve.retriever import retrieve
from src.retrieve.synthesize import synthesize
from src.graph import queries as Q

st.set_page_config(page_title="Карта знаний R&D — Норникель", layout="wide")
st.title("🗺️ Карта знаний R&D (горно-металлургия)")
st.caption("Запрос на естественном языке → граф знаний Neo4j + Yandex AI Studio")

EXAMPLES = [
    "Какие методы обессоливания воды подходят при сульфатах/хлоридах 200–300 мг/л и сухом остатке ≤1000 мг/дм³?",
    "Технические решения циркуляции католита при электроэкстракции никеля и оптимальная скорость потока?",
    "Покажите эксперименты и публикации по распределению Au, Ag, МПГ между штейном и шлаком за последние 5 лет.",
    "Способы закачки шахтных вод в глубокие горизонты: Россия vs зарубеж и их ТЭП.",
]

with st.sidebar:
    st.subheader("Примеры запросов")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state["q"] = ex

question = st.text_area("Ваш запрос:", value=st.session_state.get("q", ""), height=90)

if st.button("Найти", type="primary") and question.strip():
    with st.spinner("Разбор запроса..."):
        slots = route(question)
    driver = get_driver()
    with driver.session() as session:
        with st.spinner("Поиск по графу..."):
            context = retrieve(session, question, slots)
        with st.spinner("Синтез ответа..."):
            answer = synthesize(question, context)
        contradictions = Q.find_contradictions(session)
    driver.close()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Ответ")
        st.markdown(answer)
        if contradictions:
            st.warning("⚠️ Обнаружены противоречия в данных:")
            for c in contradictions[:5]:
                st.write(f"• {c['a']} ↔ {c['b']}: {c.get('evidence','')}")
    with col2:
        st.subheader("Распознанные слоты")
        st.json(slots)
        st.subheader(f"Источники ({len(context['sources'])})")
        for s in context["sources"]:
            st.write(f"📄 {s['doc_id']} — {s.get('geography')} / {s.get('year')}")

    with st.expander("Найденные чанки (провенанс)"):
        for ch in context["chunks"]:
            st.markdown(f"**[{ch['doc_id']} стр.{ch['page']}]** _(score {ch.get('score', 0):.3f})_")
            st.write(ch["text"][:500] + "…")
