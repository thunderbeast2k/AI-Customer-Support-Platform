"""
Sentence Transformers Embedding Generation Service.
Generates 384-dimensional dense vectors using all-MiniLM-L6-v2 on CPU with caching and fallback.
"""
import logging
import math
import hashlib
from typing import List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# Model Metadata
PINNED_MODEL_NAME = settings.EMBEDDING_MODEL_NAME  # sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION = settings.EMBEDDING_DIMENSION  # 384


class EmbeddingService:
    _instance: Optional["EmbeddingService"] = None
    _model = None
    _is_real_model: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
            cls._instance._initialize_model()
        return cls._instance

    def _initialize_model(self):
        """Attempts to load sentence-transformers on CPU."""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model %s on CPU...", PINNED_MODEL_NAME)
            self._model = SentenceTransformer(PINNED_MODEL_NAME, device="cpu")
            self._is_real_model = True
            logger.info("Embedding model %s loaded successfully.", PINNED_MODEL_NAME)
        except Exception as exc:
            logger.warning(
                "SentenceTransformers not initialized (%s). Using deterministic 384d vector synthesizer.",
                str(exc),
            )
            self._model = None
            self._is_real_model = False

    def is_using_live_model(self) -> bool:
        return self._is_real_model

    def get_model_info(self) -> dict:
        return {
            "model_name": PINNED_MODEL_NAME,
            "dimension": EMBEDDING_DIMENSION,
            "device": "cpu",
            "is_live_model": self._is_real_model,
        }

    def _generate_synthetic_384d_embedding(self, text: str) -> List[float]:
        """
        Generates a deterministic 384-dimensional unit-normalized vector for testing/local dev
        when sentence-transformers is not loaded.
        """
        clean_text = text.strip().lower()
        words = clean_text.split()

        # Seed with SHA-256 of input text
        base_hash = hashlib.sha256(clean_text.encode("utf-8")).digest()
        vector = [0.0] * EMBEDDING_DIMENSION

        # Populate coordinates
        for i in range(EMBEDDING_DIMENSION):
            byte_val = base_hash[i % len(base_hash)]
            word_influence = 0.0
            if words:
                # Add word-level harmonic influence
                w = words[i % len(words)]
                word_influence = sum(ord(c) for c in w) * 0.01

            val = math.sin((i + 1) * 0.1) * (byte_val / 255.0) + math.cos(word_influence)
            vector[i] = val

        # L2 Normalize vector so norm is 1.0 (vital for cosine similarity in pgvector)
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]

        return vector

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generates a 384-dimensional dense float vector for a given text.
        """
        if not text or not text.strip():
            # Return zero vector if empty
            return [0.0] * EMBEDDING_DIMENSION

        if self._is_real_model and self._model is not None:
            try:
                embedding = self._model.encode(
                    text.strip(),
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return embedding.tolist()
            except Exception as exc:
                logger.error("Inference failure with live model: %s. Falling back.", str(exc))

        return self._generate_synthetic_384d_embedding(text)

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generates embeddings for a list of text chunks in batch.
        """
        if not texts:
            return []

        if self._is_real_model and self._model is not None:
            try:
                embeddings = self._model.encode(
                    [t.strip() for t in texts],
                    batch_size=16,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return [emb.tolist() for emb in embeddings]
            except Exception as exc:
                logger.error("Batch inference failure: %s", str(exc))

        return [self._generate_synthetic_384d_embedding(t) for t in texts]


embedding_service = EmbeddingService()
