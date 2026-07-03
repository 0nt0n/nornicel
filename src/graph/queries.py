"""Параметризованные Cypher-шаблоны. LLM НЕ пишет Cypher — только подставляет параметры сюда.
Это ядро надёжности ретрива. Добавляйте шаблоны под новые типы вопросов.
"""
import config


def vector_search(session, query_embedding, top_k=8, geography=None, year_from=None):
    """Семантический старт: ближайшие чанки по вектору + необязательные фильтры."""
    rows = session.run(
        f"""
        CALL db.index.vector.queryNodes('{config.VECTOR_INDEX}', $k, $emb)
        YIELD node, score
        WITH node, score
        WHERE ($geo IS NULL OR node.geography = $geo)
          AND ($yf IS NULL OR node.year >= $yf)
        RETURN node.chunk_id AS chunk_id, node.text AS text, node.doc_id AS doc_id,
               node.page AS page, node.geography AS geography, node.year AS year, score
        ORDER BY score DESC
        """,
        k=top_k, emb=query_embedding, geo=geography, yf=year_from,
    )
    return [r.data() for r in rows]


def find_by_constraint(session, param, op, value=None, value_max=None,
                       geography=None, limit=25):
    """Поиск сущностей по числовому ограничению (концентрации, температуры и т.п.)."""
    rows = session.run(
        """
        MATCH (e:Entity)-[:HAS_CONSTRAINT]->(c:Constraint)
        WHERE toLower(c.param) CONTAINS toLower($param)
          AND (
             ($op='le'    AND coalesce(c.value_max, c.value_min) <= $value)
          OR ($op='ge'    AND coalesce(c.value_min, c.value_max) >= $value)
          OR ($op='eq'    AND $value >= coalesce(c.value_min, c.value_max)
                          AND $value <= coalesce(c.value_max, c.value_min))
          OR ($op='range' AND c.value_min <= coalesce($value_max, $value)
                          AND c.value_max >= $value)
          )
          AND ($geo IS NULL OR e.geography = $geo)
        OPTIONAL MATCH (ch:Chunk)-[:MENTIONS]->(e)
        WITH e, c, collect(DISTINCT {chunk_id: ch.chunk_id, text: ch.text,
                                     doc_id: ch.doc_id})[..3] AS chunks
        RETURN e.key AS entity, e.name_ru AS name_ru, e.name_en AS name_en,
               c.param AS param, c.op AS op, c.value_min AS vmin, c.value_max AS vmax,
               c.unit AS unit, c.condition AS condition, chunks
        LIMIT $limit
        """,
        param=param, op=op, value=value, value_max=value_max, geo=geography, limit=limit,
    )
    return [r.data() for r in rows]


def neighborhood(session, entity_keys, hops=2, limit=60):
    """Подграф вокруг найденных сущностей: цепочки материал->процесс->оборудование->результат."""
    rows = session.run(
        f"""
        MATCH (e:Entity) WHERE e.key IN $keys
        MATCH p=(e)-[:REL*1..{hops}]-(nb:Entity)
        WITH e, nb, relationships(p) AS rels
        RETURN e.key AS src, nb.key AS dst, nb.name_ru AS dst_ru,
               [r IN rels | r.type] AS rel_types
        LIMIT $limit
        """,
        keys=entity_keys, limit=limit,
    )
    return [r.data() for r in rows]


def find_experiments_publications(session, keywords, year_from=None, geography=None, limit=30):
    """Эксперименты и публикации по теме (для запросов 'покажите все ... за N лет')."""
    rows = session.run(
        """
        MATCH (x:Entity)
        WHERE (x:Experiment OR x:Publication)
          AND any(kw IN $kws WHERE toLower(coalesce(x.name_ru,'')+coalesce(x.name_en,'')+coalesce(x.canonical,''))
                                     CONTAINS toLower(kw))
        OPTIONAL MATCH (ch:Chunk)-[:MENTIONS]->(x)
        WITH x, collect(DISTINCT ch)[..3] AS chunks
        WHERE ($yf IS NULL OR any(c IN chunks WHERE c.year >= $yf))
          AND ($geo IS NULL OR any(c IN chunks WHERE c.geography = $geo))
        RETURN labels(x) AS labels, x.name_ru AS name_ru, x.name_en AS name_en,
               [c IN chunks | {doc_id:c.doc_id, year:c.year, geography:c.geography, text:c.text}] AS chunks
        LIMIT $limit
        """,
        kws=keywords, yf=year_from, geo=geography, limit=limit,
    )
    return [r.data() for r in rows]


def find_contradictions(session, limit=25):
    """Дёшево и эффектно: пары сущностей со связью contradicts."""
    rows = session.run(
        """
        MATCH (a:Entity)-[r:REL {type:'contradicts'}]->(b:Entity)
        RETURN a.name_ru AS a, b.name_ru AS b, r.evidence AS evidence
        LIMIT $limit
        """,
        limit=limit,
    )
    return [r.data() for r in rows]


def find_gaps(session, material_key=None, limit=25):
    """Пробелы: процессы, у которых нет привязанных экспериментов (глобально или для конкретного материала)."""
    if material_key:
        query = """
        MATCH (m:Entity {key:$mkey})-[:REL]-(p:Process)
        WHERE NOT (p)<-[:MENTIONS]-(:Chunk)<-[:FROM_CHUNK]-(:Constraint)
        RETURN p.name_ru AS process, p.canonical AS canonical
        LIMIT $limit
        """
        rows = session.run(query, mkey=material_key, limit=limit)
    else:
        query = """
        MATCH (p:Process)
        WHERE NOT (p)<-[:MENTIONS]-(:Chunk)<-[:FROM_CHUNK]-(:Constraint)
        RETURN p.name_ru AS process, p.canonical AS canonical
        LIMIT $limit
        """
        rows = session.run(query, limit=limit)
    return [r.data() for r in rows]
