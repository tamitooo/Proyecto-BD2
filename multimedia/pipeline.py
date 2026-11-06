"""ExtractFeatures: SIFT/MFCC -> codebook -> TF-IDF weighted histogram (Part 4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import numpy as np

from .histograms import word_histogram
from .mfcc import MFCCFeatureExtractor
from .quantization import KMeansCodebook
from .sift import SIFTFeatureExtractor
from .tfidf import HistogramTFIDF


@dataclass(frozen=True)
class MultimediaObject:
    modality: Literal["image", "audio"]
    source: Any
    sample_rate: int | None = None


def _object(value: MultimediaObject | Mapping[str, Any]) -> MultimediaObject:
    if isinstance(value, MultimediaObject):
        item = value
    elif isinstance(value, Mapping):
        modality = value.get("modality", value.get("type"))
        source = value.get("source", value.get("data"))
        item = MultimediaObject(modality=modality, source=source,
                                sample_rate=value.get("sample_rate"))
    else:
        raise TypeError("object must be a MultimediaObject or mapping")
    if item.modality not in ("image", "audio"):
        raise ValueError("modality must be 'image' or 'audio'")
    if item.source is None:
        raise ValueError("multimedia object is missing its source")
    return item


class MultimediaFeaturePipeline:
    """Fit once on a corpus, then turn new objects into vectors for IVF/HNSW."""

    def __init__(
        self,
        *,
        n_visual_words: int = 32,
        n_audio_words: int = 32,
        random_state: int = 0,
        max_training_descriptors: int = 50_000,
        sift: SIFTFeatureExtractor | None = None,
        mfcc: MFCCFeatureExtractor | None = None,
    ) -> None:
        if type(max_training_descriptors) is not int or max_training_descriptors < 1:
            raise ValueError("max_training_descriptors must be positive")
        self.sift = sift
        self.mfcc = mfcc or MFCCFeatureExtractor()
        self.max_training_descriptors = max_training_descriptors
        self.visual_codebook = KMeansCodebook(n_visual_words, random_state=random_state)
        self.audio_codebook = KMeansCodebook(n_audio_words, random_state=random_state + 1)
        self.visual_tfidf = HistogramTFIDF()
        self.audio_tfidf = HistogramTFIDF()
        self.random_state = random_state

    def _descriptors(self, item: MultimediaObject) -> np.ndarray:
        if item.modality == "image":
            if item.sample_rate is not None:
                raise ValueError("images must not specify sample_rate")
            if self.sift is None:
                self.sift = SIFTFeatureExtractor()
            return self.sift.extract(item.source)
        return self.mfcc.extract(item.source, sample_rate=item.sample_rate)

    def _model(self, modality: str):
        return (
            (self.visual_codebook, self.visual_tfidf)
            if modality == "image"
            else (self.audio_codebook, self.audio_tfidf)
        )

    def fit(self, objects: Iterable[MultimediaObject | Mapping[str, Any]]) -> "MultimediaFeaturePipeline":
        items = [_object(item) for item in objects]
        if not items:
            raise ValueError("at least one training object is required")
        rngs = {
            "image": np.random.default_rng(self.random_state),
            "audio": np.random.default_rng(self.random_state + 1),
        }
        pools: dict[str, np.ndarray | None] = {"image": None, "audio": None}
        priorities: dict[str, np.ndarray] = {
            "image": np.empty(0), "audio": np.empty(0),
        }

        for item in items:
            descriptors = self._descriptors(item)
            if len(descriptors) == 0:
                continue
            kind = item.modality
            scores = rngs[kind].random(len(descriptors))
            if pools[kind] is None:
                combined = descriptors
                combined_scores = scores
            else:
                combined = np.vstack((pools[kind], descriptors))
                combined_scores = np.concatenate((priorities[kind], scores))
            cap = self.max_training_descriptors
            if len(combined) > cap:
                chosen = np.argpartition(combined_scores, -cap)[-cap:]
                chosen.sort()
                combined = combined[chosen]
                combined_scores = combined_scores[chosen]
            pools[kind], priorities[kind] = combined, combined_scores

        for kind in ("image", "audio"):
            if not any(item.modality == kind for item in items):
                continue
            codebook, _ = self._model(kind)
            sample = pools[kind]
            if sample is None or len(sample) < codebook.n_words:
                raise ValueError(
                    f"not enough {kind} descriptors to train {codebook.n_words} words"
                )
            codebook.fit(sample)

        histograms: dict[str, list[np.ndarray]] = {"image": [], "audio": []}
        for item in items:
            codebook, _ = self._model(item.modality)
            assigned = codebook.predict(self._descriptors(item))
            histograms[item.modality].append(
                word_histogram(assigned, codebook.n_words, normalization=None)
            )
        for kind in ("image", "audio"):
            if histograms[kind]:
                _, weighting = self._model(kind)
                weighting.fit(np.stack(histograms[kind]))
        return self

    def extract_features(self, objeto: MultimediaObject | Mapping[str, Any]) -> np.ndarray:
        item = _object(objeto)
        codebook, weighting = self._model(item.modality)
        if codebook.centers_ is None or weighting.idf_ is None:
            raise RuntimeError(f"{item.modality} vocabulary/TF-IDF must be trained first")
        assigned = codebook.predict(self._descriptors(item))
        histogram = word_histogram(assigned, codebook.n_words, normalization=None)
        return weighting.transform(histogram)

    ExtractFeatures = extract_features

    def save(self, path: str | Path) -> Path:
        """Persist codebooks and IDF with ``np.savez`` (no pickle)."""
        if self.visual_tfidf.idf_ is None and self.audio_tfidf.idf_ is None:
            raise RuntimeError("cannot save an untrained pipeline")
        destination = Path(path)
        if destination.exists():
            raise FileExistsError(destination)
        with destination.open("xb") as output:
            np.savez_compressed(
                output,
                n_visual_words=self.visual_codebook.n_words,
                n_audio_words=self.audio_codebook.n_words,
                random_state=self.random_state,
                max_training_descriptors=self.max_training_descriptors,
                visual_centers=self.visual_codebook.centers_ if self.visual_codebook.centers_ is not None else np.empty((0, 0)),
                audio_centers=self.audio_codebook.centers_ if self.audio_codebook.centers_ is not None else np.empty((0, 0)),
                visual_idf=self.visual_tfidf.idf_ if self.visual_tfidf.idf_ is not None else np.empty(0),
                audio_idf=self.audio_tfidf.idf_ if self.audio_tfidf.idf_ is not None else np.empty(0),
                visual_documents=self.visual_tfidf.document_count_,
                audio_documents=self.audio_tfidf.document_count_,
            )
        return destination

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        sift: SIFTFeatureExtractor | None = None,
        mfcc: MFCCFeatureExtractor | None = None,
    ) -> "MultimediaFeaturePipeline":
        with np.load(path, allow_pickle=False) as data:
            model = cls(
                n_visual_words=int(data["n_visual_words"]),
                n_audio_words=int(data["n_audio_words"]),
                random_state=int(data["random_state"]),
                max_training_descriptors=int(data["max_training_descriptors"]),
                sift=sift, mfcc=mfcc,
            )
            for kind in ("visual", "audio"):
                centers = np.array(data[f"{kind}_centers"], dtype=np.float32)
                idf = np.array(data[f"{kind}_idf"], dtype=np.float64)
                codebook = model.visual_codebook if kind == "visual" else model.audio_codebook
                weighting = model.visual_tfidf if kind == "visual" else model.audio_tfidf
                if centers.size:
                    if centers.ndim != 2 or centers.shape[0] != codebook.n_words or len(idf) != codebook.n_words:
                        raise ValueError("corrupt multimedia vocabulary dimensions")
                    codebook.centers_ = np.ascontiguousarray(centers)
                    weighting.idf_ = idf
                    weighting.document_count_ = int(data[f"{kind}_documents"])
                elif idf.size:
                    raise ValueError("TF-IDF without a fitted vocabulary")
        return model


def ExtractFeatures(
    objeto: MultimediaObject | Mapping[str, Any],
    *,
    pipeline: MultimediaFeaturePipeline,
) -> np.ndarray:
    """Requires a trained pipeline: retraining would change the vector space of the index."""
    if not isinstance(pipeline, MultimediaFeaturePipeline):
        raise TypeError("pipeline must be a MultimediaFeaturePipeline")
    return pipeline.extract_features(objeto)
