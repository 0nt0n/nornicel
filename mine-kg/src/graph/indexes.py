"""Индексы и ограничения Neo4j. Векторный индекс создаётся под размерность эмбеддера."""
import config


def create_constraints(session):
    session.run(
        "CREATE CONSTRAINT entity_key IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.key IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE"
    )


def create_vector_index(session, dim: int):
    session.run(
        f"""
        CREATE VECTOR INDEX {config.VECTOR_INDEX} IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {{ indexConfig: {{
            `vector.dimensions`: {dim},
            `vector.similarity_function`: 'cosine'
        }} }}
        """
    )


def create_fulltext_index(session):
    session.run(
        f"CREATE FULLTEXT INDEX {config.FULLTEXT_INDEX} IF NOT EXISTS "
        "FOR (c:Chunk) ON EACH [c.text]"
    )


def init_schema(session, dim: int):
    create_constraints(session)
    create_vector_index(session, dim)
    create_fulltext_index(session)
