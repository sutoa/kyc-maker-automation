"""Contract tests for ExtractedPerson and ExtractorCriticFeedback models."""

import pytest
from pydantic import ValidationError

from src.models.person import ExtractedPerson
from src.models.workflow import ExtractionIssueSimple, ExtractorCriticFeedback


class TestExtractedPersonFlat:
    """ExtractedPerson must match extractor.md JSON example exactly."""

    def test_minimal_valid_person(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=3,
        )
        assert person.first_name == "Hans"
        assert person.last_name == "Müller"
        assert person.doc_name == "register.pdf"
        assert person.page_number == 3

    def test_optional_job_title(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
        )
        assert person.job_title == "Managing Director"
        assert person.job_title_original == "Geschäftsführer"

    def test_missing_first_name_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="",
                last_name="Müller",
                doc_name="register.pdf",
                page_number=1,
            )

    def test_missing_last_name_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="Hans",
                last_name="",
                doc_name="register.pdf",
                page_number=1,
            )

    def test_page_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="Hans",
                last_name="Müller",
                doc_name="register.pdf",
                page_number=0,
            )

    def test_no_extraction_id_field(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
        )
        assert not hasattr(person, "extraction_id")

    def test_no_source_references_field(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
        )
        assert not hasattr(person, "source_references")


class TestExtractorCriticFeedback:
    """ExtractorCriticFeedback must match extractor_critic.md JSON example."""

    def test_pass_with_no_issues(self):
        feedback = ExtractorCriticFeedback(
            status="pass",
            issues=[],
            feedback="All records are valid.",
        )
        assert feedback.status == "pass"
        assert feedback.issues == []

    def test_fail_with_issues(self):
        feedback = ExtractorCriticFeedback(
            status="fail",
            issues=[
                ExtractionIssueSimple(
                    first_name="Hans",
                    last_name="Müller",
                    issue_description="Missing page number",
                    severity="error",
                )
            ],
            feedback="1 record has missing page number.",
        )
        assert feedback.status == "fail"
        assert len(feedback.issues) == 1
        assert feedback.issues[0].severity == "error"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ExtractorCriticFeedback(
                status="unknown",
                issues=[],
                feedback="test",
            )

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            ExtractionIssueSimple(
                first_name="Hans",
                last_name="Müller",
                issue_description="Bad",
                severity="critical",  # only "error" | "warning" allowed
            )
