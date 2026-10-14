from types import SimpleNamespace

import numpy as np

from hr_screening.semantic import LocalSemanticEncoder


class Tensor(np.ndarray):
    def mean(self, dim=None):
        return np.asarray(np.asarray(self).mean(axis=dim)).view(Tensor)

    def clamp(self, low, high):
        return np.clip(self, low, high)


def test_empty_query_returns_zeros_without_loading_or_encoding():
    encoder = LocalSemanticEncoder.__new__(LocalSemanticEncoder)
    scores, metadata = encoder.compare(' \n\t', ['Python', '', 'PostgreSQL'])
    assert scores == [0.0, 0.0, 0.0]
    assert metadata == {'query_truncated': False, 'truncated_documents': []}


def test_only_empty_documents_return_zeros_without_encoding_query():
    encoder = LocalSemanticEncoder.__new__(LocalSemanticEncoder)
    assert encoder.compare('Python', ['', ' \t'])[0] == [0.0, 0.0]
    assert encoder.compare('Python', [])[0] == []


def test_mixed_empty_documents_keep_nonempty_similarity_and_original_indices():
    encoder = LocalSemanticEncoder.__new__(LocalSemanticEncoder)
    encoder.torch = SimpleNamespace(nn=SimpleNamespace(functional=SimpleNamespace(normalize=lambda vector, **kwargs: vector)))
    def chunks(text):
        assert text.strip(), 'Empty text must never reach tokenization or encoding'
        return [text], text == 'matching'
    encoder._chunks = chunks
    encoder._encode = lambda parts: np.asarray([[0.0, 1.0] if part == 'unrelated' else [1.0, 0.0] for part in parts]).view(Tensor)
    scores, metadata = encoder.compare('Python', ['', 'matching', ' \n', 'unrelated'])
    assert scores == [0.0, 1.0, 0.0, 0.0]
    assert metadata == {'query_truncated': False, 'truncated_documents': [1]}
