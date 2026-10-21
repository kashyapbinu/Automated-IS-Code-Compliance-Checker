import hashlib
import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schemas import DrawingType, Extraction, ExtractedParam, ParamStatus, get_schema  # noqa: E402


class FakeEmbedder:
    """Bag-of-words hashing embedder: deterministic, no model download, good enough for retrieval tests."""

    dim = 256

    def _vec(self, text):
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9.]+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


def make_extraction(drawing_type: DrawingType, **values) -> Extraction:
    params = []
    for spec in get_schema(drawing_type):
        value = values.get(spec.key)
        params.append(ExtractedParam(
            key=spec.key, label=spec.label, value=value,
            status=ParamStatus.FOUND if value else ParamStatus.MISSING,
        ))
    return Extraction(drawing_type=drawing_type, params=params)
