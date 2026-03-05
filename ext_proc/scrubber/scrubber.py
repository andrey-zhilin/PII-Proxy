"""PII scrubber using Presidio Analyzer, Anonymizer, and Structured.

Supports:
- Plain-text bodies: uses AnalyzerEngine + AnonymizerEngine directly.
- JSON bodies:       uses presidio-structured's StructuredEngine which
                     walks every string leaf and anonymises in place.

The spaCy model is controlled by the SPACY_MODEL env-var
(default: en_core_web_lg).  Make sure the model is downloaded before
starting the service:

    python -m spacy download en_core_web_lg
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_structured import StructuredEngine, JsonAnalysisBuilder, JsonDataProcessor

log = logging.getLogger(__name__)

_SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_lg")


def _build_analyzer() -> AnalyzerEngine:
    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": _SPACY_MODEL}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_config)
    nlp_engine = provider.create_engine()
    return AnalyzerEngine(nlp_engine=nlp_engine)


class PiiScrubber:
    """Scrubs PII from plain-text and JSON response bodies.

    A single instance is intended to be created at startup and reused for the
    lifetime of the process (model loading is expensive).
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language
        log.info("Loading spaCy model '%s' …", _SPACY_MODEL)
        self._analyzer = _build_analyzer()
        self._anonymizer = AnonymizerEngine()
        self._structured_engine = StructuredEngine(data_processor=JsonDataProcessor())
        self._json_builder = JsonAnalysisBuilder(analyzer=self._analyzer)
        log.info("PiiScrubber ready.")

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def scrub_text(self, text: str) -> str:
        """Anonymize PII in a plain-text string."""
        results = self._analyzer.analyze(text=text, language=self.language)
        if not results:
            return text
        return self._anonymizer.anonymize(text=text, analyzer_results=results).text

    def scrub_json(
        self, data: dict[str, Any] | list[Any]
    ) -> dict[str, Any] | list[Any]:
        """Anonymize PII in all string fields of a JSON-like dict/list.

        Top-level lists are handled by processing each element recursively;
        ``presidio_structured``'s ``JsonAnalysisBuilder`` only accepts dicts.
        """
        if isinstance(data, list):
            return [
                self.scrub_json(item) if isinstance(item, (dict, list)) else item
                for item in data
            ]
        analysis = self._json_builder.generate_analysis(data, language=self.language)
        return self._structured_engine.anonymize(data, analysis)

    def scrub_bytes(self, body: bytes, content_type: str = "") -> bytes:
        """Main entry point called per response body.

        Detects whether the payload is JSON or plain text, routes accordingly,
        and returns scrubbed bytes with the same encoding as the input.
        Binary (non-UTF-8) payloads are returned unchanged.
        """
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return body  # binary – nothing to scrub

        ct = content_type.lower()
        if "json" in ct or _looks_like_json(text):
            try:
                data = json.loads(text)
                if isinstance(data, (dict, list)):
                    scrubbed = self.scrub_json(data)
                    return json.dumps(scrubbed, ensure_ascii=False).encode("utf-8")
            except (json.JSONDecodeError, ValueError):
                pass  # fall through to plain-text scrubbing

        return self.scrub_text(text).encode("utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _looks_like_json(text: str) -> bool:
    """Cheap heuristic: does the text look like it starts a JSON object/array?"""
    stripped = text.strip()
    return stripped.startswith(("{", "["))
