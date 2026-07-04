"""Streamlit-интерфейс: карта знаний R&D.

Запрос на естественном языке -> ReAct-цепочка (4 уровня рассуждений) ->
ответ с источниками + интерактивный подграф знаний.

Запуск:
    streamlit run src/app/streamlit_app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

# Streamlit Community Cloud отдаёт секреты через st.secrets, а config.py читает
# os.environ. Пробрасываем ДО импорта проектных модулей (config исполняется на импорте).
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)):
            os.environ.setdefault(_k, str(_v))
except Exception:  # noqa: BLE001
    pass  # локально secrets.toml может отсутствовать — не страшно

import streamlit.components.v1 as components
from pyvis.network import Network

from src.graph.loader import get_driver
from src.retrieve.router import route
from src.retrieve.react_chain import multi_level_retrieve, synthesize_multi
from src.graph import queries as Q

st.set_page_config(
    page_title="Карта знаний R&D — Норникель",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------- палитра
# Категориальная палитра типов сущностей — валидирована для тёмной поверхности
# (dataviz: lightness band, chroma floor, contrast >= 3:1; CVD 10.3 в допустимой
# полосе — вторичное кодирование обеспечивают подписи узлов и текстовая легенда)
ENTITY_COLORS = {
    "Material": "#3987e5", "Process": "#199e70", "Equipment": "#c98500",
    "Experiment": "#008300", "Property": "#9085e9", "Expert": "#e66767",
    "Publication": "#d55181", "Facility": "#d95926",
    "Conclusion": "#0ea3b5", "Recommendation": "#a8842a",
}
ENTITY_LABELS_RU = {
    "Material": "Материал", "Process": "Процесс", "Equipment": "Оборудование",
    "Experiment": "Эксперимент", "Property": "Свойство", "Expert": "Эксперт",
    "Publication": "Публикация", "Facility": "Установка",
    "Conclusion": "Вывод", "Recommendation": "Рекомендация",
}
ACCENT = "#3987e5"
SURFACE = "#111413"
CARD_BG = "#1a1f1e"
BORDER = "#2c3331"
TEXT_MUTED = "#9aa5a1"

LEVEL_META = {
    1: ("🔍", "Разведка", "Гибридный поиск (вектор + полнотекст) и анализ покрытия запроса"),
    2: ("🔬", "Углубление", "Дополнительные подзапросы по непокрытым аспектам"),
    3: ("⚖️", "Перекрёстная проверка", "Поиск противоречий между источниками"),
    4: ("🧩", "Финальный синтез", "Сборка всего контекста в экспертный ответ"),
}

st.markdown(f"""
<style>
  /* убираем «прототипную» обвязку Streamlit — выглядит как продукт, а не демо */
  #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
  [data-testid="stStatusWidget"] {{ display: none !important; }}

  html, body, [class*="css"] {{
    font-family: -apple-system, "Segoe UI", "Inter", Roboto, Helvetica, Arial, sans-serif;
  }}
  .stApp {{
    background:
      radial-gradient(900px 500px at 12% -8%, rgba(57,135,229,.10), transparent 60%),
      radial-gradient(700px 500px at 100% 0%, rgba(25,158,112,.08), transparent 55%),
      {SURFACE};
  }}
  .block-container {{ padding-top: 1.4rem; max-width: 1360px; }}

  /* заголовки секций — тонкий акцентный маркер слева */
  .stMarkdown h3 {{
    font-size: 1.12rem; margin: 1.4rem 0 .5rem; padding-left: .7rem;
    border-left: 3px solid {ACCENT};
  }}

  /* герой-шапка */
  .hero {{
    background: linear-gradient(135deg, #16294356 0%, #10201c99 55%, {SURFACE} 100%);
    border: 1px solid {BORDER}; border-radius: 18px;
    padding: 1.5rem 1.9rem; margin-bottom: 1.1rem;
    box-shadow: 0 10px 40px -24px rgba(0,0,0,.7);
  }}
  .hero h1 {{ margin: 0; font-size: 1.7rem; font-weight: 700; letter-spacing: .2px; }}
  .hero p {{ margin: .4rem 0 0; color: {TEXT_MUTED}; font-size: .96rem; max-width: 820px; }}
  .stat-pills {{ display: flex; gap: .55rem; flex-wrap: wrap; margin-top: 1rem; }}
  .pill {{
    background: rgba(57,135,229,.12); border: 1px solid rgba(57,135,229,.35);
    color: #cfe3fb; border-radius: 999px; padding: .3rem .85rem; font-size: .82rem;
    font-variant-numeric: tabular-nums;
  }}

  /* вкладки */
  .stTabs [data-baseweb="tab-list"] {{ gap: .3rem; border-bottom: 1px solid {BORDER}; }}
  .stTabs [data-baseweb="tab"] {{
    padding: .5rem 1rem; border-radius: 10px 10px 0 0; font-weight: 600;
  }}
  .stTabs [aria-selected="true"] {{ background: {CARD_BG}; color: #dbe7ff; }}

  /* кнопки */
  .stButton > button, .stDownloadButton > button {{
    border-radius: 10px; border: 1px solid {BORDER}; font-weight: 500;
    transition: border-color .15s, transform .05s, background .15s;
  }}
  .stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: {ACCENT}; color: #dbe7ff;
  }}
  .stButton > button:active {{ transform: translateY(1px); }}
  .stButton > button[kind="primary"] {{
    background: linear-gradient(180deg, #3f92ee, {ACCENT}); border: 0;
    box-shadow: 0 8px 24px -12px rgba(57,135,229,.9);
  }}

  /* поля ввода и экспандеры */
  .stTextArea textarea {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px;
  }}
  [data-testid="stExpander"] {{
    border: 1px solid {BORDER}; border-radius: 12px; background: {CARD_BG};
  }}

  /* карточки уровней ReAct */
  .lvl-card {{
    border: 1px solid {BORDER}; border-left: 4px solid {ACCENT};
    background: {CARD_BG}; border-radius: 12px;
    padding: .9rem 1.1rem; margin-bottom: .6rem;
  }}
  .lvl-head {{ font-weight: 600; font-size: 1rem; margin-bottom: .3rem; }}
  .lvl-sub {{ color: {TEXT_MUTED}; font-size: .82rem; margin-bottom: .5rem; }}
  .chip {{
    display: inline-block; background: rgba(255,255,255,.06);
    border: 1px solid {BORDER}; border-radius: 999px;
    padding: .12rem .65rem; margin: .12rem .25rem .12rem 0; font-size: .8rem;
  }}
  .chip.miss {{ border-color: rgba(230,103,103,.5); color: #f0b5b5; }}
  .chip.ok   {{ border-color: rgba(25,158,112,.5);  color: #a9dcc7; }}

  /* карточка ответа */
  .answer-card {{
    border: 1px solid {BORDER}; background: {CARD_BG};
    border-radius: 14px; padding: 1.2rem 1.4rem;
    box-shadow: 0 10px 40px -28px rgba(0,0,0,.7);
  }}

  /* легенда графа */
  .legend {{ display: flex; flex-wrap: wrap; gap: .5rem .9rem; margin: .4rem 0 .6rem; }}
  .legend span {{ font-size: .82rem; color: {TEXT_MUTED}; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%;
          margin-right:.35rem; vertical-align:-1px; }}
  iframe {{ border-radius: 12px; border: 1px solid {BORDER}; }}

  /* источники */
  .src-card {{
    border: 1px solid {BORDER}; background: {CARD_BG}; border-radius: 10px;
    padding: .55rem .8rem; margin-bottom: .45rem; font-size: .86rem;
    transition: border-color .15s;
  }}
  .src-card:hover {{ border-color: {ACCENT}; }}
  .src-meta {{ color: {TEXT_MUTED}; font-size: .78rem; }}
  .conf-high {{ color: #7fd6a8; }} .conf-medium {{ color: #e8c46a; }} .conf-low {{ color: #f0938a; }}
  div[data-testid="stMetric"] {{
    background: {CARD_BG}; border: 1px solid {BORDER};
    border-radius: 12px; padding: .7rem .9rem;
  }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- данные
@st.cache_resource
def _driver():
    return get_driver()


@st.cache_data(ttl=60)
def _graph_stats():
    try:
        with _driver().session() as s:
            row = s.run(
                """
                OPTIONAL MATCH (c:Chunk) WITH count(c) AS chunks
                OPTIONAL MATCH (e:Entity) WITH chunks, count(e) AS entities
                OPTIONAL MATCH (con:Constraint) WITH chunks, entities, count(con) AS constraints
                OPTIONAL MATCH (d:Chunk) RETURN chunks, entities, constraints,
                       count(DISTINCT d.doc_id) AS docs
                """
            ).single()
            return dict(row) if row else {}
    except Exception:  # noqa: BLE001
        return {}


def _entity_type(labels):
    for l in labels or []:
        if l != "Entity":
            return l
    return "Entity"


@st.cache_resource(show_spinner="Первый запуск: строю граф из data/processed/ …")
def _ensure_graph():
    """Автосборка графа из закоммиченных JSON, если он пуст (деплой «через git»).
    Выполняется один раз на процесс. Если граф уже наполнен (Neo4j персистентный) —
    мгновенный no-op. Ошибки не роняют UI — просто показываем статус."""
    try:
        with _driver().session() as s:
            n = s.run("MATCH (c:Chunk) RETURN count(c) AS n").single()["n"]
    except Exception as e:  # noqa: BLE001
        return {"state": "no_db", "error": str(e)}
    if n and n > 0:
        return {"state": "ready", "chunks": n}
    try:
        from src.graph.loader import load_all_processed
        res = load_all_processed()
        return {"state": "built", **res}
    except Exception as e:  # noqa: BLE001
        return {"state": "build_error", "error": str(e)}


# ---------------------------------------------------------------- шапка
_boot = _ensure_graph()
if _boot.get("state") == "no_db":
    st.error("Нет связи с Neo4j. Проверь секреты NEO4J_URI / NEO4J_USER / "
             "NEO4J_PASSWORD в настройках приложения.")
elif _boot.get("state") == "build_error":
    st.warning("Граф пуст, автосборка не удалась: " + _boot.get("error", "") +
               "  — проверь ключи Yandex (нужны для эмбеддингов).")
stats = _graph_stats()
pills = ""
if stats:
    pills = (
        f'<div class="stat-pills">'
        f'<span class="pill">📄 Документов: {stats.get("docs", 0)}</span>'
        f'<span class="pill">🧩 Фрагментов: {stats.get("chunks", 0)}</span>'
        f'<span class="pill">🔗 Сущностей: {stats.get("entities", 0)}</span>'
        f'<span class="pill">🔢 Ограничений: {stats.get("constraints", 0)}</span>'
        f'</div>'
    )
st.markdown(f"""
<div class="hero">
  <h1>🧭 Карта знаний R&D — горно-металлургия</h1>
  <p>Вопрос на естественном языке → 4-уровневая ReAct-цепочка рассуждений по графу знаний
     Neo4j → ответ с источниками, числами и уровнем достоверности</p>
  {pills}
</div>
""", unsafe_allow_html=True)

tab_search, tab_analytics = st.tabs(["🔎 Поиск", "📊 Аналитика графа"])

EXAMPLES = [
    "Какие методы обессоливания воды подходят при сульфатах/хлоридах 200–300 мг/л и сухом остатке ≤1000 мг/дм³?",
    "Технические решения циркуляции католита при электроэкстракции никеля и оптимальная скорость потока?",
    "Покажите эксперименты и публикации по распределению Au, Ag, МПГ между штейном и шлаком за последние 5 лет.",
    "Способы закачки шахтных вод в глубокие горизонты: Россия vs зарубеж и их ТЭП.",
]

# ---------------------------------------------------------------- поиск
with tab_search:
    st.caption("Примеры запросов — нажми, чтобы подставить:")
    ex_cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if ex_cols[i % 2].button(ex, width="stretch", key=f"ex{i}"):
            st.session_state["q"] = ex

    question = st.text_area(
        "Ваш запрос:", value=st.session_state.get("q", ""),
        height=90, placeholder="Например: какие реагенты применяются при флотации медно-никелевых руд?",
    )
    run = st.button("🚀 Найти ответ", type="primary", width="stretch")

    if run and question.strip():
        try:
            with st.status("🧠 ReAct-цепочка работает...", expanded=True) as status:
                st.write("Разбор запроса на структурные слоты...")
                slots = route(question)

                def _progress(level, msg):
                    icon, name, _ = LEVEL_META.get(level, ("•", f"Уровень {level}", ""))
                    st.write(f"{icon} **Уровень {level} · {name}:** {msg}")

                with _driver().session() as session:
                    context = multi_level_retrieve(session, question, slots,
                                                   progress_cb=_progress)
                    contradictions = Q.find_contradictions(session)
                st.write("📝 Синтез финального ответа...")
                answer = synthesize_multi(question, context)
                status.update(label="✅ Готово", state="complete", expanded=False)

            st.session_state["last"] = {
                "question": question, "slots": slots, "context": context,
                "answer": answer, "contradictions": contradictions,
            }
        except Exception as e:  # noqa: BLE001
            st.error(f"Ошибка выполнения запроса: {e}")

    last = st.session_state.get("last")
    if last:
        context, answer = last["context"], last["answer"]
        col_main, col_side = st.columns([2.1, 1])

        with col_main:
            st.markdown("### 💬 Ответ")
            st.markdown(f'<div class="answer-card">', unsafe_allow_html=True)
            st.markdown(answer)
            st.markdown("</div>", unsafe_allow_html=True)
            st.download_button(
                "📥 Скачать ответ (Markdown)",
                data=f"# Вопрос\n{last['question']}\n\n# Ответ\n{answer}",
                file_name="answer.md", mime="text/markdown",
            )
            # ---------- цепочка рассуждений ReAct
            st.markdown("### 🧠 Цепочка рассуждений")
            for lvl in context.get("levels", []):
                ln = lvl.get("level", 0)
                icon, name, sub = LEVEL_META.get(ln, ("•", lvl.get("action", ""), ""))
                chips = ""
                for a in lvl.get("covered_aspects", []):
                    chips += f'<span class="chip ok">✓ {a}</span>'
                for a in lvl.get("missing_aspects", []):
                    chips += f'<span class="chip miss">✗ {a}</span>'
                for sq in lvl.get("sub_queries_used", []):
                    chips += f'<span class="chip">→ {sq}</span>'
                for f in lvl.get("verified_facts", [])[:4]:
                    chips += f'<span class="chip ok">✓ {f}</span>'
                facts_meta = []
                if lvl.get("chunks_found") is not None:
                    facts_meta.append(f"найдено фрагментов: {lvl['chunks_found']}")
                if lvl.get("extra_chunks"):
                    facts_meta.append(f"доп. фрагментов: {lvl['extra_chunks']}")
                if lvl.get("contradictions_found"):
                    facts_meta.append(f"противоречий: {lvl['contradictions_found']}")
                if lvl.get("total_unique_chunks") is not None:
                    facts_meta.append(f"итого уникальных: {lvl['total_unique_chunks']}")
                meta = (" · ".join(facts_meta)) or sub
                st.markdown(f"""
                <div class="lvl-card">
                  <div class="lvl-head">{icon} Уровень {ln} · {name}</div>
                  <div class="lvl-sub">{meta}</div>
                  <div>{lvl.get("reasoning", "")}</div>
                  <div>{chips}</div>
                </div>
                """, unsafe_allow_html=True)

            # ---------- противоречия
            if last.get("contradictions"):
                st.warning("⚠️ В графе знаний зафиксированы противоречия:")
                for c in last["contradictions"][:5]:
                    st.write(f"• {c['a']} ↔ {c['b']}: {c.get('evidence', '')}")

            # ---------- сравнение РФ / зарубеж
            comparison = context.get("comparison_chunks")
            if comparison:
                st.markdown("### 🌍 Отечественная vs зарубежная практика")
                cru, cf = st.columns(2)
                for col, key, title in ((cru, "RU", "🇷🇺 РФ"), (cf, "foreign", "🌍 Зарубеж")):
                    with col:
                        st.markdown(f"**{title}**")
                        for ch in comparison.get(key, [])[:5]:
                            st.markdown(
                                f'<div class="src-card">{ch["doc_id"]}'
                                f'<div class="src-meta">{ch.get("year") or "год неизвестен"}</div></div>',
                                unsafe_allow_html=True,
                            )

            # ---------- подграф знаний
            st.markdown("### 🕸️ Подграф знаний")
            if context.get("entities"):
                legend = '<div class="legend">'
                used_types = {_entity_type(e.get("labels")) for e in context["entities"]}
                for t in ENTITY_COLORS:
                    if t in used_types:
                        legend += (f'<span><i class="dot" style="background:{ENTITY_COLORS[t]}"></i>'
                                   f'{ENTITY_LABELS_RU.get(t, t)}</span>')
                legend += "</div>"
                st.markdown(legend, unsafe_allow_html=True)

                net = Network(height="480px", width="100%", bgcolor=SURFACE,
                              font_color="#e8e6df", directed=True)
                net.set_options("""
                {
                  "physics": {"barnesHut": {"gravitationalConstant": -12000,
                              "springLength": 140, "damping": 0.25},
                              "stabilization": {"iterations": 120}},
                  "edges": {"color": {"color": "#3a4441"}, "smooth": true,
                            "font": {"size": 10, "color": "#9aa5a1", "strokeWidth": 0}},
                  "nodes": {"font": {"size": 13}, "borderWidth": 0, "shape": "dot", "size": 14}
                }
                """)
                added = set()

                def _add_node(key, name_ru, name_en, labels):
                    if not key or key in added:
                        return
                    added.add(key)
                    etype = _entity_type(labels)
                    net.add_node(key, label=(name_ru or name_en or key)[:40],
                                 color=ENTITY_COLORS.get(etype, "#9aa5a1"),
                                 title=f"{ENTITY_LABELS_RU.get(etype, etype)}: {name_ru or name_en or key}")

                for e in context["entities"]:
                    _add_node(e["key"], e.get("name_ru"), e.get("name_en"), e.get("labels"))
                for edge in context.get("subgraph_edges", []):
                    _add_node(edge["src"], edge.get("src_ru"), edge.get("src_en"), edge.get("src_labels"))
                    _add_node(edge["dst"], edge.get("dst_ru"), edge.get("dst_en"), edge.get("dst_labels"))
                    net.add_edge(edge["src"], edge["dst"],
                                 label=" / ".join(edge.get("rel_types") or []))

                net.save_graph("graph.html")
                with open("graph.html", encoding="utf-8") as f:
                    components.html(f.read(), height=500)
            else:
                st.info("Сущности не найдены в контексте — граф пуст.")

            # ---------- пробелы
            if context.get("gaps"):
                with st.expander(f"🕳️ Пробелы в исследованиях ({len(context['gaps'])})"):
                    st.caption("Процессы без экспериментальной проверки в корпусе — кандидаты на новые НИР")
                    for g in context["gaps"][:10]:
                        st.write(f"• {g.get('process') or g.get('canonical')}")

        with col_side:
            m1, m2 = st.columns(2)
            m1.metric("Источников", len(context.get("sources", [])))
            m2.metric("Фрагментов", len(context.get("chunks", [])))
            l3 = next((l for l in context.get("levels", []) if l.get("level") == 3), {})
            if l3.get("confidence"):
                st.metric("Достоверность (кросс-проверка)", l3["confidence"])

            st.markdown("#### 📄 Источники")
            for s in context.get("sources", [])[:12]:
                geo_icon = {"RU": "🇷🇺", "foreign": "🌍"}.get(s.get("geography"), "❔")
                st.markdown(
                    f'<div class="src-card">{geo_icon} {s["doc_id"]}'
                    f'<div class="src-meta">{s.get("year") or "год неизвестен"}</div></div>',
                    unsafe_allow_html=True,
                )

            with st.expander("Распознанные слоты запроса"):
                st.json(last["slots"])

            with st.expander("Провенанс: найденные чанки"):
                for ch in context.get("chunks", [])[:15]:
                    conf = ch.get("confidence", "medium")
                    badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                    st.markdown(f"**{ch['doc_id']} · стр.{ch.get('page', '?')}** "
                                f"{badge} <span class='conf-{conf}'>{conf}</span> "
                                f"· score {ch.get('score', 0):.3f}",
                                unsafe_allow_html=True)
                    st.caption(ch.get("text", "")[:350] + "…")

# ---------------------------------------------------------------- аналитика
with tab_analytics:
    try:
        with _driver().session() as session:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📄 Документов", stats.get("docs", 0))
            c2.metric("🧩 Фрагментов", stats.get("chunks", 0))
            c3.metric("🔗 Сущностей", stats.get("entities", 0))
            c4.metric("🔢 Ограничений", stats.get("constraints", 0))

            st.markdown("---")
            colA, colB = st.columns([1.2, 1])

            with colA:
                st.subheader("Сущности по типам")
                rows = session.run(
                    """
                    MATCH (e:Entity) UNWIND labels(e) AS l
                    WITH l, count(*) AS n WHERE l <> 'Entity'
                    RETURN l AS type, n ORDER BY n DESC
                    """
                ).data()
                if rows:
                    import altair as alt
                    import pandas as pd
                    df = pd.DataFrame(rows)
                    df["type_ru"] = df["type"].map(lambda t: ENTITY_LABELS_RU.get(t, t))
                    # одна серия -> один цвет (магнитуда), прямые подписи значений
                    chart = (
                        alt.Chart(df).mark_bar(color=ACCENT, cornerRadiusEnd=4, height=18)
                        .encode(
                            x=alt.X("n:Q", title=None, axis=alt.Axis(grid=False)),
                            y=alt.Y("type_ru:N", sort="-x", title=None),
                            tooltip=[alt.Tooltip("type_ru:N", title="Тип"),
                                     alt.Tooltip("n:Q", title="Количество")],
                        )
                    )
                    labels = chart.mark_text(align="left", dx=4, color="#e8e6df").encode(text="n:Q")
                    st.altair_chart(
                        (chart + labels).configure_view(strokeWidth=0)
                        .configure_axis(labelColor="#9aa5a1", domainColor="#2c3331"),
                        width="stretch",
                    )
                else:
                    st.info("Граф пока пуст — загрузите данные (run_pipeline.py --load-only).")

            with colB:
                st.subheader("Самые связанные сущности")
                hubs = session.run(
                    """
                    MATCH (e:Entity)
                    WITH e, count{(e)-[:REL]-()} + count{(e)<-[:MENTIONS]-()} AS degree
                    WHERE degree > 0
                    RETURN coalesce(e.name_ru, e.name_en, e.key) AS name,
                           [l IN labels(e) WHERE l <> 'Entity'][0] AS type, degree
                    ORDER BY degree DESC LIMIT 10
                    """
                ).data()
                if hubs:
                    for h in hubs:
                        color = ENTITY_COLORS.get(h["type"], "#9aa5a1")
                        st.markdown(
                            f'<div class="src-card"><i class="dot" style="background:{color}"></i>'
                            f'{h["name"]}<div class="src-meta">'
                            f'{ENTITY_LABELS_RU.get(h["type"], h["type"] or "—")} · связей: {h["degree"]}'
                            f'</div></div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("Нет данных о связях.")

            st.markdown("---")
            colC, colD = st.columns(2)
            with colC:
                st.subheader("⚠️ Противоречия в данных")
                contras = Q.find_contradictions(session)
                if contras:
                    for c in contras[:8]:
                        st.write(f"• {c['a']} ↔ {c['b']}: {c.get('evidence', '')[:120]}")
                else:
                    st.caption("Противоречий типа contradicts в графе не зафиксировано.")
            with colD:
                st.subheader("🕳️ Пробелы в знаниях")
                gaps = Q.find_gaps(session)
                if gaps:
                    for g in gaps[:8]:
                        st.write(f"• {g.get('process') or g.get('canonical')}")
                else:
                    st.caption("Явных пробелов не найдено (или мало данных).")

            st.markdown("---")
            st.subheader("📦 Экспорт")
            st.caption("JSON-LD — RDF-совместимый формат (FAIR): граф можно загрузить "
                       "в Apache Jena / GraphDB или опубликовать как Linked Data.")
            if st.button("Сформировать JSON-LD"):
                import json as _json
                from scripts.export_jsonld import export as _export_jsonld
                doc = _export_jsonld(session)
                st.download_button(
                    "📥 Скачать knowledge_graph.jsonld",
                    data=_json.dumps(doc, ensure_ascii=False, indent=2),
                    file_name="knowledge_graph.jsonld", mime="application/ld+json",
                )
    except Exception as e:  # noqa: BLE001
        st.error(f"Ошибка подключения к Neo4j: {e}")
