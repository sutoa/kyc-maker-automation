"""Unit tests for output persistence.

Tests for saving and loading workflow output JSON files.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.services.storage import (
    load_workflow_output,
    persist_workflow_output,
    save_output_json,
)


class TestSaveOutputJson:
    """Tests for save_output_json function."""

    def test_save_creates_file(self, tmp_path):
        """Test that save_output_json creates a JSON file."""
        output_data = {"test": "data", "value": 123}

        file_path = save_output_json("workflow-123", output_data, tmp_path)

        assert file_path.exists()
        assert file_path.suffix == ".json"

    def test_save_creates_directory_if_not_exists(self, tmp_path):
        """Test that save creates output directory if it doesn't exist."""
        output_dir = tmp_path / "nested" / "output"
        output_data = {"test": "data"}

        file_path = save_output_json("workflow-456", output_data, output_dir)

        assert file_path.exists()
        assert output_dir.exists()

    def test_saved_file_contains_valid_json(self, tmp_path):
        """Test that saved file contains valid JSON."""
        output_data = {"workflow_id": "test-123", "csm_list": []}

        file_path = save_output_json("test-123", output_data, tmp_path)

        with open(file_path, "r") as f:
            loaded = json.load(f)

        assert loaded == output_data

    def test_filename_includes_workflow_id(self, tmp_path):
        """Test that filename includes the workflow ID."""
        output_data = {"test": "data"}

        file_path = save_output_json("my-workflow-abc", output_data, tmp_path)

        assert "my-workflow-abc" in file_path.name

    def test_save_handles_unicode(self, tmp_path):
        """Test that save handles unicode characters correctly."""
        output_data = {
            "name": "Hans Müller",
            "location": "Frankfurt am Main",
            "title": "Geschäftsführer",
        }

        file_path = save_output_json("unicode-test", output_data, tmp_path)

        with open(file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["name"] == "Hans Müller"
        assert loaded["title"] == "Geschäftsführer"


class TestPersistWorkflowOutput:
    """Tests for persist_workflow_output function."""

    def test_persist_creates_complete_structure(self, tmp_path):
        """Test that persist creates complete output structure."""
        document_manifest = [
            {"filename": "doc1.pdf", "file_type": "PDF", "page_count": 5}
        ]
        csm_list = [{"person_id": "p1", "first_name": "Hans", "classification": "CSM"}]
        non_csm_list = [
            {"person_id": "p2", "first_name": "Anna", "classification": "NON_CSM"}
        ]

        file_path = persist_workflow_output(
            workflow_id="test-workflow",
            document_manifest=document_manifest,
            csm_list=csm_list,
            non_csm_list=non_csm_list,
            output_dir=tmp_path,
        )

        with open(file_path, "r") as f:
            output = json.load(f)

        assert output["workflow_id"] == "test-workflow"
        assert "generated_at" in output
        assert output["document_manifest"] == document_manifest
        assert output["csm_list"] == csm_list
        assert output["non_csm_list"] == non_csm_list

    def test_persist_includes_summary(self, tmp_path):
        """Test that persist includes summary statistics."""
        document_manifest = [
            {"filename": "doc1.pdf"},
            {"filename": "doc2.pdf"},
        ]
        csm_list = [{"person_id": "p1"}, {"person_id": "p2"}]
        non_csm_list = [{"person_id": "p3"}]

        file_path = persist_workflow_output(
            workflow_id="summary-test",
            document_manifest=document_manifest,
            csm_list=csm_list,
            non_csm_list=non_csm_list,
            output_dir=tmp_path,
        )

        with open(file_path, "r") as f:
            output = json.load(f)

        assert output["summary"]["total_documents"] == 2
        assert output["summary"]["total_csm"] == 2
        assert output["summary"]["total_non_csm"] == 1

    def test_persist_empty_lists(self, tmp_path):
        """Test that persist handles empty lists correctly."""
        file_path = persist_workflow_output(
            workflow_id="empty-test",
            document_manifest=[],
            csm_list=[],
            non_csm_list=[],
            output_dir=tmp_path,
        )

        with open(file_path, "r") as f:
            output = json.load(f)

        assert output["document_manifest"] == []
        assert output["csm_list"] == []
        assert output["non_csm_list"] == []
        assert output["summary"]["total_documents"] == 0
        assert output["summary"]["total_csm"] == 0
        assert output["summary"]["total_non_csm"] == 0


class TestLoadWorkflowOutput:
    """Tests for load_workflow_output function."""

    def test_load_returns_saved_data(self, tmp_path):
        """Test that load returns the saved data."""
        output_data = {
            "workflow_id": "load-test",
            "csm_list": [{"name": "Test"}],
            "non_csm_list": [],
        }
        file_path = tmp_path / "test_output.json"
        with open(file_path, "w") as f:
            json.dump(output_data, f)

        loaded = load_workflow_output(file_path)

        assert loaded == output_data

    def test_load_raises_on_missing_file(self, tmp_path):
        """Test that load raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_workflow_output(tmp_path / "nonexistent.json")

    def test_load_raises_on_invalid_json(self, tmp_path):
        """Test that load raises JSONDecodeError for invalid JSON."""
        file_path = tmp_path / "invalid.json"
        with open(file_path, "w") as f:
            f.write("not valid json")

        with pytest.raises(json.JSONDecodeError):
            load_workflow_output(file_path)

    def test_load_preserves_unicode(self, tmp_path):
        """Test that load preserves unicode characters."""
        output_data = {"name": "Hans Müller", "title": "Geschäftsführer"}
        file_path = tmp_path / "unicode.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False)

        loaded = load_workflow_output(file_path)

        assert loaded["name"] == "Hans Müller"
        assert loaded["title"] == "Geschäftsführer"


class TestOutputPersistenceRoundTrip:
    """End-to-end tests for output persistence."""

    def test_save_and_load_round_trip(self, tmp_path):
        """Test complete save and load round trip."""
        document_manifest = [
            {"filename": "doc1.pdf", "file_type": "PDF", "page_count": 10}
        ]
        csm_list = [
            {
                "person_id": "p1",
                "first_name": "Hans",
                "last_name": "Müller",
                "classification": "CSM",
            }
        ]
        non_csm_list = [
            {
                "person_id": "p2",
                "first_name": "Anna",
                "last_name": "Schmidt",
                "classification": "NON_CSM",
            }
        ]

        file_path = persist_workflow_output(
            workflow_id="round-trip-test",
            document_manifest=document_manifest,
            csm_list=csm_list,
            non_csm_list=non_csm_list,
            output_dir=tmp_path,
        )

        loaded = load_workflow_output(file_path)

        assert loaded["workflow_id"] == "round-trip-test"
        assert loaded["document_manifest"] == document_manifest
        assert loaded["csm_list"] == csm_list
        assert loaded["non_csm_list"] == non_csm_list
