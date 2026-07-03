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
from src.retrieve.react_chain import multi_level_retrieve, synthesize_multi
from src.graph import queries as Q

st.set_page_config(page_title="Карта знаний R&D — Норникель", layout="wide")
st.title(" Карта знаний R&D (горно-металлургия)")
st.caption("Запрос на естественном языке → граф знаний Neo4j + Yandex AI Studio (ReAct 4-уровневый)")

ENTITY_COLORS = {
    "Material": "#4C9AFF", "Process": "#36B37E", "Equipment": "#FFAB00",
    "Property": "#6554C0", "Experiment": "#00B8D9", "Publication": "#97A0AF",
    "Expert": "#FF5630", "Facility": "#79E2F2",
    "Conclusion": "#DE350B", "Recommendation": "#FFC400",
}


def _entity_type(labels):
    for l in labels or []:
        if l != "Entity":
            return l
    return "Entity"

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

# Вкладки
selected_tab = st.tabs(["Поиск", "Аналитика и Дашборд"])

LEVEL_ICONS = {1: "🔍", 2: "🔬", 3: "✅", 4: "📝"}
LEVEL_NAMES = {1: "Разведка", 2: "Углубление", 3: "Перекрёстная проверка", 4: "Финальный синтез"}

with selected_tab[0]: # Поиск
    question = st.text_area("Ваш запрос:", value=st.session_state.get("q", ""), height=90)
    
    if st.button("Найти", type="primary") and question.strip():
        with st.spinner("Разбор запроса..."):
            slots = route(question)
        driver = get_driver()
        with driver.session() as session:
            with st.spinner("Многоуровневый поиск по графу (ReAct)..."):
                context = multi_level_retrieve(session, question, slots)
            with st.spinner("Синтез ответа..."):
                answer = synthesize_multi(question, context)
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
            
            # Цепочка рассуждений ReAct
            if context.get("levels"):
                st.subheader("Цепочка рассуждений (ReAct)")
                for lvl in context["levels"]:
                    ln = lvl.get("level", 0)
                    icon = LEVEL_ICONS.get(ln, "🔹")
                    name = LEVEL_NAMES.get(ln, lvl.get("action", ""))
                    with st.expander(f"{icon} Уровень {ln}: {name}", expanded=(ln == 1)):
                        st.write(f"**Действие:** {lvl.get('action', '')}")
                        if lvl.get("reasoning"):
                            st.write(f"**Рассуждение:** {lvl['reasoning']}")
                        if lvl.get("chunks_found") is not None:
                            st.write(f"**Найдено фрагментов:** {lvl['chunks_found']}")
                        if lvl.get("covered_aspects"):
                            st.write("**Покрытые аспекты:**")
                            for a in lvl["covered_aspects"]:
                                st.write(f"  ✓ {a}")
                        if lvl.get("missing_aspects"):
                            st.write("**Непокрытые аспекты:**")
                            for a in lvl["missing_aspects"]:
                                st.write(f"  ✗ {a}")
                        if lvl.get("sub_queries_used"):
                            st.write("**Подзапросы:**")
                            for sq in lvl["sub_queries_used"]:
                                st.write(f"  → {sq}")
                        if lvl.get("verified_facts"):
                            st.write("**Подтверждённые факты:**")
                            for f in lvl["verified_facts"][:5]:
                                st.write(f"  ✓ {f}")
                        if lvl.get("contradictions_found"):
                            st.warning(f"Найдено противоречий: {lvl['contradictions_found']}")
                        if lvl.get("total_unique_chunks") is not None:
                            st.metric("Итого уникальных фрагментов", lvl["total_unique_chunks"])
            
            if contradictions:
                st.warning("Обнаружены противоречия в данных:")
                for c in contradictions[:5]:
                    st.write(f"• {c['a']} ↔ {c['b']}: {c.get('evidence','')}")

            if context.get("comparison_chunks"):
                st.subheader("Сравнение: отечественная vs зарубежная практика")
                cru, cforeign = st.columns(2)
                with cru:
                    st.markdown("**🇷🇺 РФ**")
                    for ch in context["comparison_chunks"].get("RU", [])[:5]:
                        st.caption(f"{ch['doc_id']} ({ch.get('year') or '?'})")
                with cforeign:
                    st.markdown("**Зарубеж**")
                    for ch in context["comparison_chunks"].get("foreign", [])[:5]:
                        st.caption(f"{ch['doc_id']} ({ch.get('year') or '?'})")

            if context.get("gaps"):
                with st.expander(f"Пробелы в исследованиях ({len(context['gaps'])})"):
                    for g in context["gaps"][:10]:
                        st.write(f"• {g.get('process') or g.get('canonical')}")

            # Pyvis: реальный подграф сущностей вокруг найденного контекста
            # (материал -> процесс -> оборудование -> результат)
            st.subheader("Подграф знаний (сущности и связи)")
            if context.get("entities"):
                net = Network(height='450px', width='100%', bgcolor='#ffffff',
                               font_color='black', directed=True)
                added = set()

                def _add_node(key, name_ru, name_en, labels):
                    if not key or key in added:
                        return
                    added.add(key)
                    etype = _entity_type(labels)
                    net.add_node(key, label=(name_ru or name_en or key)[:40],
                                 color=ENTITY_COLORS.get(etype, "#97A0AF"),
                                 title=f"{etype}: {name_ru or name_en or key}")

                for e in context["entities"]:
                    _add_node(e["key"], e.get("name_ru"), e.get("name_en"), e.get("labels"))

                for edge in context.get("subgraph_edges", []):
                    _add_node(edge["src"], edge.get("src_ru"), edge.get("src_en"), edge.get("src_labels"))
                    _add_node(edge["dst"], edge.get("dst_ru"), edge.get("dst_en"), edge.get("dst_labels"))
                    net.add_edge(edge["src"], edge["dst"],
                                 label=" / ".join(edge.get("rel_types") or []), color="#9AA5B1")

                net.save_graph("graph.html")
                with open("graph.html", "r", encoding="utf-8") as HtmlFile:
                    components.html(HtmlFile.read(), height=470)
            else:
                st.info("Сущности не найдены в контексте — граф пуст.")

        with col2:
            st.subheader("Распознанные слоты")
            st.json(slots)
            st.subheader(f"Источники ({len(context['sources'])})")
            for s in context["sources"]:
                st.write(f" {s['doc_id']} — {s.get('geography')} / {s.get('year')}")
    
        with st.expander("Найденные чанки (провенанс)"):
            for ch in context["chunks"]:
                conf = ch.get("confidence", "medium")
                conf_badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                st.markdown(f"**[{ch['doc_id']} стр.{ch['page']}]** "
                            f"_(score {ch.get('score', 0):.3f}, достоверность {conf_badge} {conf})_")
                st.write(ch["text"][:500] + "…")

if len(selected_tab) > 1:
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
