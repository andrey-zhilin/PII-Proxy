# Idea

Stage 1: Patterns + Checksums (Fast Path)
  ├─ Structured PII detection
  │    ├─ Emails
  │    ├─ Phone numbers
  │    ├─ IBAN / Credit Card numbers (Luhn check)
  │    ├─ National IDs (if applicable)
  │    └─ IP addresses
  └─ Rule-based recognizers for high precision

Stage 2: NER / Domain Model
  ├─ Contextual PII detection
  │    ├─ Person names
  │    ├─ Locations
  │    ├─ Organizations
  │    └─ Addresses in prose
  └─ Disambiguation of cases regex can’t handle reliably

Stage 3: LLM "Hard-Case" Pass
  ├─ Applied only to segments with low confidence or residual risk
  ├─ Targets:
  │    ├─ Non-standard mentions
  │    ├─ Indirect identifiers
  │    └─ Cases where meaning/context matters more than format
  └─ Higher computational cost but better privacy–utility trade-off


# Architecture


Envoy -> envoy.filters.http.ext_processor -> PII Proxy (gRPC) -> Stage 1 (Regex/Rules) -> Stage 2 (NER) -> Stage 3 (LLM) -> Response to Envoy