"""Эмбеддинги за одним интерфейсом. Бэкенд переключается config.EMBED_BACKEND.

  yandex : text-search-doc / text-search-query через emb://<folder>/... (единый провайдер, в контуре)
  e5     : локальный intfloat/multilingual-e5-base (бесплатно, офлайн; ставится через sentence-transformers)

Размерность вектора определяется автоматически по первому запросу — под неё создаётся индекс в Neo4j.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import config
from src.yandex import get_client, wait_rate_limit


class Embedder:
    def embed_documents(self, texts):  # -> list[list[float]]
        raise NotImplementedError

    def embed_query(self, text):        # -> list[float]
        raise NotImplementedError

    def dim(self) -> int:
        return len(self.embed_query("проба"))


class YandexEmbedder(Embedder):
    def __init__(self):
        self.client = get_client()
        self.folder = config.YANDEX_FOLDER_ID

    def _emb_uri(self, model):
        return f"emb://{self.folder}/{model}/latest"

    def _embed_one(self, text, model):
        wait_rate_limit()
        # У Yandex эмбеддинги считаются по одному тексту за вызов.
        r = self.client.embeddings.create(model=self._emb_uri(model), input=text, encoding_format="float")
        return r.data[0].embedding

    def embed_documents(self, texts):
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            # map сохраняет порядок результатов == порядку texts
            return list(pool.map(lambda t: self._embed_one(t, config.EMBED_MODEL_DOC), texts))

    def embed_query(self, text):
        return self._embed_one(text, config.EMBED_MODEL_QUERY)


class E5Embedder(Embedder):
    """Локальный fallback. e5 требует префиксов 'passage:' / 'query:'."""
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(config.E5_MODEL)

    def embed_documents(self, texts):
        vecs = self.model.encode([f"passage: {t}" for t in texts], normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    def embed_query(self, text):
        v = self.model.encode(f"query: {text}", normalize_embeddings=True)
        return v.tolist()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if config.EMBED_BACKEND == "e5":
        return E5Embedder()
    return YandexEmbedder()
