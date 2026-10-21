"""BGE embeddings (normalised). Queries get the BGE retrieval instruction prefix; passages do not."""
from functools import lru_cache
from typing import List

from src import config


class Embedder:
    def __init__(self, model_name: str = None, query_instruction: str = None):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or config.EMBEDDING_MODEL
        self.query_instruction = config.QUERY_INSTRUCTION if query_instruction is None else query_instruction
        self.model = SentenceTransformer(self.model_name)

    def embed_documents(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        vectors = self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=len(texts) > 64)
        return vectors.tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(self.query_instruction + text, normalize_embeddings=True).tolist()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()
