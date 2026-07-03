"""Streamlit-интерфейс: запрос на естественном языке -> ответ + источники + подграф.

Запуск:
    streamlit run src/app/streamlit_app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

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

# RBAC
with st.sidebar:
    st.subheader("Управление доступом")
    role = st.selectbox("Роль пользователя", ["Исследователь", "Аналитик", "Администратор"])
    st.info(f"Текущая роль: **{role}**")
    
    st.subheader("Примеры запросов")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state["q"] = ex

# Вкладки
tabs = ["Поиск"]
if role in ["Аналитик", "Администратор"]:
    tabs.append("Аналитика и Дашборд")

selected_tab = st.tabs(tabs)

with selected_tab[0]: # Поиск
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
            
            # Export
            st.download_button(
                label="📥 Скачать ответ (Markdown)",
                data=f"# Вопрос\n{question}\n\n# Ответ\n{answer}",
                file_name="answer.md",
                mime="text/markdown"
            )
            
            if contradictions:
                st.warning("⚠️ Обнаружены противоречия в данных:")
                for c in contradictions[:5]:
                    st.write(f"• {c['a']} ↔ {c['b']}: {c.get('evidence','')}")
                    
            # Pyvis Graph
            st.subheader("Визуализация графа (Контекст)")
            if context["chunks"]:
                net = Network(height='400px', width='100%', bgcolor='#ffffff', font_color='black')
                # Simple graph construction for context chunks
                net.add_node("Query", label="Запрос", color="#ff4b4b", title=question)
                
                for doc in context["sources"]:
                    doc_id = doc['doc_id']
                    net.add_node(doc_id, label=doc_id, color="#00ffbf", title="Документ")
                    net.add_edge("Query", doc_id)
                    
                for i, ch in enumerate(context["chunks"][:5]): # limit to 5 for viz
                    ch_id = f"chunk_{i}"
                    net.add_node(ch_id, label=f"Чанк {i+1}", color="#5302e0", title=ch["text"][:100])
                    net.add_edge(ch["doc_id"], ch_id)
                
                # Save and read pyvis html
                net.save_graph("graph.html")
                HtmlFile = open("graph.html", 'r', encoding='utf-8')
                source_code = HtmlFile.read() 
                components.html(source_code, height=420)
                
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

if role in ["Аналитик", "Администратор"] and len(selected_tab) > 1:
    with selected_tab[1]: # Аналитика
        st.header("Аналитика графа знаний")
        driver = get_driver()
        try:
            with driver.session() as session:
                st.subheader("Общая статистика узлов")
                # Query node counts
                res = session.run("MATCH (n) RETURN labels(n)[0] as label, count(n) as count").data()
                if res:
                    stats = {r['label']: r['count'] for r in res if r['label']}
                    if stats:
                        cols = st.columns(min(len(stats), 4))
                        for i, (k, v) in enumerate(stats.items()):
                            cols[i % 4].metric(k, v)
                else:
                    st.info("Граф пока пуст.")
                
                st.markdown("---")
                st.subheader("Пробелы в знаниях (Слабо изученные зоны)")
                gaps = Q.find_gaps(session)
                if gaps:
                    st.dataframe(gaps)
                else:
                    st.info("Явных пробелов не найдено (или недостаточно данных для анализа).")
        except Exception as e:
            st.error(f"Ошибка подключения к Neo4j: {e}")
        finally:
            driver.close()
