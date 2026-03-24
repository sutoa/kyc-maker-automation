"""Agent implementations for KYC document processing workflow.

This module exports all agent functions and their input/output contracts:
- Extractor: Extracts person data from documents
- Critics (1, 2, 3): Validate extraction, reconciliation, and classification
- Reconciler: Deduplicates person records
- Classifier: Classifies persons as CSM/NON_CSM
- Formatter: Formats final output
"""

from src.agents.classifier import (
    ClassifierInput,
    ClassifierOutput,
    classifier_agent,
    classify_persons,
)
from src.agents.critic import (
    Critic1Input,
    Critic1Output,
    Critic2Input,
    Critic2Output,
    Critic3Input,
    Critic3Output,
    critic_1_agent,
    critic_2_agent,
    critic_3_agent,
    validate_classification,
    validate_extraction,
    validate_reconciliation,
)
from src.agents.extractor import (
    ExtractorInput,
    ExtractorOutput,
    extract_persons,
    extractor_agent,
)
from src.agents.formatter import (
    FormatterInput,
    FormatterOutput,
    format_output,
    formatter_agent,
)
from src.agents.reconciler import (
    ReconcilerInput,
    ReconcilerOutput,
    reconcile_persons,
    reconciler_agent,
)

__all__ = [
    # Extractor
    "ExtractorInput",
    "ExtractorOutput",
    "extractor_agent",
    "extract_persons",
    # Critics
    "Critic1Input",
    "Critic1Output",
    "Critic2Input",
    "Critic2Output",
    "Critic3Input",
    "Critic3Output",
    "critic_1_agent",
    "critic_2_agent",
    "critic_3_agent",
    "validate_extraction",
    "validate_reconciliation",
    "validate_classification",
    # Reconciler
    "ReconcilerInput",
    "ReconcilerOutput",
    "reconciler_agent",
    "reconcile_persons",
    # Classifier
    "ClassifierInput",
    "ClassifierOutput",
    "classifier_agent",
    "classify_persons",
    # Formatter
    "FormatterInput",
    "FormatterOutput",
    "formatter_agent",
    "format_output",
]
