"""BM25 over the small fixed document set, in the standard library only.

No embeddings, no vector store, no dependency: the corpus is a handful of short
markdown files, so a lexical ranker written here is enough and its behaviour is
easy to explain in a test. A query that shares no term with any document returns
no passages at all — the app then says it does not know instead of guessing.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
# A query word this long may also match a longer word it is the start of.
PREFIX_MIN_LENGTH = 4
# A heading is the document's own summary, so its words count this many times.
TITLE_BOOST = 2
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
)


def tokenize(text: str) -> list[str]:
    return [word for word in TOKEN.findall(text.lower()) if word not in STOPWORDS]


@dataclass(frozen=True)
class Document:
    name: str
    text: str


def load_documents(folder: Path) -> list[Document]:
    """Every markdown file, by name; a missing folder is an error, not a guess."""
    documents = [
        Document(name=path.name, text=path.read_text(encoding="utf-8"))
        for path in sorted(folder.glob("*.md"))
    ]
    if not documents:
        raise FileNotFoundError(f"no markdown documents in {folder}")
    return documents


class Retriever:
    """Okapi BM25 with the usual constants, over the documents it was given."""

    def __init__(
        self, documents: list[Document], k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.documents = documents
        self.k1 = k1
        self.b = b
        self._tokens = [tokenize(document.text) for document in documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._average = sum(self._lengths) / max(len(self._lengths), 1)
        self._frequencies = [
            Counter(tokens)
            + Counter(
                {
                    word: TITLE_BOOST * count
                    for word, count in Counter(
                        tokenize(document.text.splitlines()[0] if document.text else "")
                    ).items()
                }
            )
            for tokens, document in zip(self._tokens, documents, strict=True)
        ]
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            for term in set(tokens):
                self._document_frequency[term] += 1

    def _idf(self, term: str) -> float:
        total = len(self.documents)
        frequency = self._document_frequency.get(term, 0)
        return math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))

    @staticmethod
    def _frequency(frequencies: Counter[str], term: str) -> int:
        """Exact matches, plus a word the query is a prefix of (ship → shipping).

        No stemming library and no new dependency: a short prefix rule keeps
        "ship" finding "shipping", and the minimum length keeps it from matching
        everything.
        """
        total = frequencies.get(term, 0)
        if len(term) >= PREFIX_MIN_LENGTH:
            total += sum(
                count
                for word, count in frequencies.items()
                if word != term and word.startswith(term)
            )
        return total

    def scores(self, question: str) -> list[float]:
        terms = tokenize(question)
        result: list[float] = []
        for index, frequencies in enumerate(self._frequencies):
            length = self._lengths[index] or 1
            score = 0.0
            for term in terms:
                frequency = self._frequency(frequencies, term)
                if not frequency:
                    continue
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / (self._average or 1)
                )
                score += self._idf(term) * frequency * (self.k1 + 1) / denominator
            result.append(score)
        return result

    def search(self, question: str, top_k: int = 3) -> list[Document]:
        """The best passages, or none when the question shares no term at all."""
        scores = self.scores(question)
        ranked = sorted(
            range(len(self.documents)), key=lambda i: scores[i], reverse=True
        )
        best = [index for index in ranked if scores[index] > 0][:top_k]
        return [self.documents[index] for index in best]

    def irrelevant(
        self, question: str, seed: int = 20261114, top_k: int = 3
    ) -> list[Document]:
        """Passages chosen without the question: the ``wrong_docs`` test mode.

        The seed makes the wrong answer the same on every start, so a test can
        assert on it; the choice ignores the question entirely.
        """
        pool = list(self.documents)
        random.Random(seed).shuffle(pool)
        return pool[:top_k]
