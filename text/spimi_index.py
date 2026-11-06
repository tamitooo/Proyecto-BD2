"""Term lookup on the final SPIMI index; postings stay on disk until requested."""

from __future__ import annotations

import json
from pathlib import Path

from .preprocessing import DEFAULT_PREPROCESSOR, TextPreprocessor
from .spimi_merge import LEXICON_FILENAME, POSTINGS_FILENAME
from .spimi_storage import DiskDocumentId, document_id_sort_key


class SPIMIInvertedIndex:
    """Lexicon in memory (term -> byte offset, df); one seek per term lookup."""

    def __init__(
        self,
        directory: str | Path,
        *,
        preprocessor: TextPreprocessor = DEFAULT_PREPROCESSOR,
    ) -> None:
        if not isinstance(preprocessor, TextPreprocessor):
            raise TypeError("preprocessor must be a TextPreprocessor")
        self.preprocessor = preprocessor
        self.directory = Path(directory)
        self.postings_path = self.directory / POSTINGS_FILENAME
        self.lexicon_path = self.directory / LEXICON_FILENAME
        self._lexicon: dict[str, tuple[int, int]] = {}

        if not self.postings_path.is_file():
            raise FileNotFoundError(self.postings_path)

        previous_term: str | None = None
        previous_offset = -1
        with self.lexicon_path.open("r", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict) or set(item) != {"t", "o", "df"}:
                        raise ValueError("expected keys t, o, df")
                    term, offset, df = item["t"], item["o"], item["df"]
                    if not isinstance(term, str) or not term:
                        raise ValueError("invalid term")
                    if type(offset) is not int or offset < 0:
                        raise ValueError("invalid byte offset")
                    if type(df) is not int or df <= 0:
                        raise ValueError("invalid document frequency")
                    if previous_term is not None and term <= previous_term:
                        raise ValueError("lexicon is not strictly sorted")
                    if offset <= previous_offset:
                        raise ValueError("lexicon offsets are not increasing")
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"invalid SPIMI lexicon line {number}: {exc}"
                    ) from exc
                self._lexicon[term] = (offset, df)
                previous_term, previous_offset = term, offset

    def _term(self, raw_term: object) -> str | None:
        terms = self.preprocessor.tokenize(raw_term)
        return terms[0] if len(terms) == 1 else None

    @property
    def vocabulary_size(self) -> int:
        return len(self._lexicon)

    def document_frequency(self, term: object) -> int:
        normalized = self._term(term)
        return self._lexicon.get(normalized, (0, 0))[1]

    def search_term(self, term: object) -> dict[DiskDocumentId, int]:
        """Return postings for a single term (case/Unicode normalized)."""
        normalized = self._term(term)
        location = self._lexicon.get(normalized)
        if location is None:
            return {}
        offset, df = location

        postings: dict[DiskDocumentId, int] = {}
        previous_id_key = None
        with self.postings_path.open("rb") as stream:
            stream.seek(offset)
            for _ in range(df):
                line = stream.readline()
                try:
                    if not line:
                        raise ValueError("unexpected end of postings file")
                    item = json.loads(line)
                    if not isinstance(item, dict) or set(item) != {"t", "d", "f"}:
                        raise ValueError("invalid posting record")
                    if item["t"] != normalized:
                        raise ValueError("lexicon points to a different term")
                    doc_id, frequency = item["d"], item["f"]
                    id_key = document_id_sort_key(doc_id)
                    if type(frequency) is not int or frequency < 1:
                        raise ValueError("invalid posting frequency")
                    if previous_id_key is not None and id_key <= previous_id_key:
                        raise ValueError("postings are not strictly sorted")
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"corrupt SPIMI posting for {normalized!r}: {exc}"
                    ) from exc
                postings[doc_id] = frequency
                previous_id_key = id_key
        return postings

    lookup = search_term
