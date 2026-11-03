
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterator


# Unicode letters and numbers, excluding underscores.
# NFKC normalization is applied before matching.
_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)


@dataclass(frozen=True)
class TextPreprocessor:
    """Shared preprocessing for indexing and searching.

    Default settings preserve accents and stopwords to remain
    compatible with the existing SQL MATCH implementation. (That I have yet not fixed because I am lazy)

    A language-aware stemmer may be injected when needed. (ONLY FOR TESTING)
    """

    stopwords: frozenset[str] = frozenset()
    strip_accents: bool = False
    min_token_length: int = 1
    stemmer: Callable[[str], str] | None = field(
        default=None, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        if type(self.min_token_length) is not int or self.min_token_length < 1:
            raise ValueError("min_token_length must be a positive integer")

        if not isinstance(self.strip_accents, bool):
            raise TypeError("strip_accents must be a bool")

        if isinstance(self.stopwords, str):
            raise TypeError(
                "stopwords must be an iterable of words, not a string"
            )

        if self.stemmer is not None and not callable(self.stemmer):
            raise TypeError("stemmer must be callable")

        normalized: set[str] = set()

        for word in self.stopwords:
            if not isinstance(word, str):
                raise TypeError("each stopword must be a string")

            term = self._normalize(word)

            if _TOKEN_PATTERN.fullmatch(term) is None:
                raise ValueError(f"invalid stopword: {word!r}")

            normalized.add(term)

        object.__setattr__(
            self, "stopwords", frozenset(normalized)
        )

    def _normalize(self, value: str) -> str:
        """Normalize Unicode and apply folding."""
        result = unicodedata.normalize("NFKC", value).casefold()

        if self.strip_accents:
            result = "".join(
                char
                for char in unicodedata.normalize("NFKD", result)
                if unicodedata.category(char) != "Mn"
            )

        return unicodedata.normalize("NFC", result)

    def iter_tokens(self, value: object | None) -> Iterator[str]:
        """Yield normalized tokens without storing a token list.

        Suitable for processing documents incrementally during SPIMI
        block construction. (NOT FOR BETA)
        """
        if value is None:
            return

        normalized_text = self._normalize(str(value))

        for match in _TOKEN_PATTERN.finditer(normalized_text):
            term = match.group()

            # Stopword removal precedes stemming.
            if term in self.stopwords:
                continue

            if self.stemmer is not None:
                stemmed = self.stemmer(term)

                if not isinstance(stemmed, str):
                    raise TypeError("stemmer must return a string")

                term = self._normalize(stemmed)

                if _TOKEN_PATTERN.fullmatch(term) is None:
                    raise ValueError(
                        "stemmer must return one nonempty token"
                    )

            if len(term) >= self.min_token_length:
                yield term

    def tokenize(self, value: object | None) -> list[str]:
        """Return normalized terms, preserving order and repetitions."""
        return list(self.iter_tokens(value))


# Default instance shared with the SQL query layer.
DEFAULT_PREPROCESSOR = TextPreprocessor()


def tokenize(value: object | None) -> list[str]:
    """Compatibility entry point for SQL MATCH and SPIMI.
    Taken value is converted in output for a list of strings."""
    return DEFAULT_PREPROCESSOR.tokenize(value)
