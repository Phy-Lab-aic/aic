"""Tests for path traversal security in dataset_service.load_dataset()."""

import pytest
from backend.services.dataset_service import DatasetService


@pytest.fixture
def service():
    """Fresh DatasetService instance for each test."""
    return DatasetService()


class TestPathTraversalSecurity:
    """Verify allowed_dataset_roots validation blocks path traversal attacks."""

    def test_path_traversal_with_dot_dot(self, service):
        """../  sequences that escape the allowed root must be rejected."""
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/tmp/hf-mounts/../../etc/passwd")

    def test_absolute_path_outside_allowed_roots(self, service):
        """Absolute paths outside allowed roots must be rejected."""
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/etc/passwd")

    def test_allowed_root_substring_not_sufficient(self, service):
        """A path whose string starts with an allowed root but is not under it must be rejected.

        e.g. /tmp/hf-mounts-evil/dataset starts with "/tmp/hf-mounts" as a string
        but is NOT a child directory. The check uses Path.parents, not startswith.
        """
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/tmp/hf-mounts-evil/dataset")

    def test_valid_path_under_allowed_root(self, service):
        """A path under an allowed root should pass the path validation.

        It may raise FileNotFoundError because the directory doesn't exist,
        but it must NOT raise ValueError for the path check.
        """
        with pytest.raises(FileNotFoundError):
            service.load_dataset("/tmp/hf-mounts/valid-dataset")

    def test_empty_path(self, service):
        """An empty path resolves to cwd, which should not be under allowed roots."""
        with pytest.raises((ValueError, FileNotFoundError)):
            service.load_dataset("")
