
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterator


# Unicode letters and numbers, excluding underscores.
_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)


@dataclass(frozen=True)
class TextPreprocessor:
    """Shared preprocessing for indexing and searching; defaults keep accents and stopwords."""

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
        """Yield normalized tokens lazily, without building a list."""
        if value is None:
            return

        normalized_text = self._normalize(str(value))

        for match in _TOKEN_PATTERN.finditer(normalized_text):
            term = match.group()

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


DEFAULT_PREPROCESSOR = TextPreprocessor()


def tokenize(value: object | None) -> list[str]:
    """Tokenize with the default preprocessor shared by SQL MATCH and SPIMI."""
    return DEFAULT_PREPROCESSOR.tokenize(value)
