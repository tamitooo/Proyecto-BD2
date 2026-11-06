"""Extraction of local image/audio descriptors for the multimedia pipeline."""

from .sift import SIFTFeatureExtractor, extract_sift_descriptors
from .mfcc import MFCCFeatureExtractor, extract_mfcc_descriptors
from .quantization import KMeansCodebook
from .histograms import word_histogram
from .tfidf import HistogramTFIDF
from .pipeline import ExtractFeatures, MultimediaFeaturePipeline, MultimediaObject

__all__ = [
    "SIFTFeatureExtractor", "extract_sift_descriptors",
    "MFCCFeatureExtractor", "extract_mfcc_descriptors",
    "KMeansCodebook", "word_histogram", "HistogramTFIDF",
    "MultimediaObject", "MultimediaFeaturePipeline", "ExtractFeatures",
]
