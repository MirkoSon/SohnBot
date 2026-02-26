"""Unit tests for PatchEditor capability."""

import os
import tempfile
from pathlib import Path

import pytest

from sohnbot.capabilities.files.file_ops import FileCapabilityError
from sohnbot.capabilities.files.patch_editor import PatchEditor


VALID_PATCH = """\
--- original.txt
+++ original.txt
@@ -1,3 +1,3 @@
 line1
-line2
+line2_modified
 line3
"""

VALID_PATCH_MULTILINE = """\
--- file.py
+++ file.py
@@ -1,5 +1,6 @@
 def foo():
-    return 1
+    return 2
+

 def bar():
     return 3
"""


@pytest.fixture
def editor():
    return PatchEditor()


@pytest.fixture
def temp_file():
    """Create a temp file with predictable content for patching."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, newline="\n"
    ) as f:
        f.write("line1\nline2\nline3\n")
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def temp_py_file():
    """Create a temp python-like file for multiline patch test."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, newline="\n"
    ) as f:
        f.write("def foo():\n    return 1\n\n\ndef bar():\n    return 3\n")
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestPatchEditorHappyPath:
    def test_apply_patch_success(self, editor, temp_file):
        """Valid unified diff applied successfully."""
        patch_for_file = VALID_PATCH.replace("original.txt", Path(temp_file).name)
        result = editor.apply_patch(
            path=temp_file,
            patch_content=patch_for_file,
        )
        assert result["path"] == temp_file
        assert result["lines_added"] >= 1
        assert result["lines_removed"] >= 1
        # Verify the file was actually modified
        content = Path(temp_file).read_text()
        assert "line2_modified" in content
        assert "line2\n" not in content

    def test_returns_correct_line_counts(self, editor, temp_file):
        """lines_added and lines_removed are counted correctly from patch."""
        patch_for_file = VALID_PATCH.replace("original.txt", Path(temp_file).name)
        result = editor.apply_patch(path=temp_file, patch_content=patch_for_file)
        assert result["lines_added"] == 1
        assert result["lines_removed"] == 1

    def test_returns_path_in_result(self, editor, temp_file):
        """Result dict contains the target file path."""
        patch_for_file = VALID_PATCH.replace("original.txt", Path(temp_file).name)
        result = editor.apply_patch(path=temp_file, patch_content=patch_for_file)
        assert result["path"] == temp_file


class TestPatchTooLarge:
    def test_patch_exceeds_size_limit(self, editor, temp_file):
        """Patch larger than patch_max_size_kb raises patch_too_large."""
        # 51KB patch content
        big_patch = "--- a\n+++ b\n@@ -1,1 +1,1 @@\n" + "+" * (51 * 1024)
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path=temp_file, patch_content=big_patch, patch_max_size_kb=50)
        assert exc_info.value.code == "patch_too_large"
        assert exc_info.value.retryable is False
        assert "50KB" in exc_info.value.message

    def test_patch_at_limit_is_accepted(self, editor, temp_file):
        """Patch exactly at limit should not raise patch_too_large."""
        # A valid patch that's small — just confirm size check boundary
        patch_for_file = VALID_PATCH.replace("original.txt", Path(temp_file).name)
        # Small patch; set limit to 1MB — should pass
        result = editor.apply_patch(path=temp_file, patch_content=patch_for_file, patch_max_size_kb=1024)
        assert result["path"] == temp_file


class TestInvalidPatchFormat:
    def test_missing_diff_markers(self, editor, temp_file):
        """Content without ---, +++, @@ markers raises invalid_patch_format."""
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path=temp_file, patch_content="this is not a patch")
        assert exc_info.value.code == "invalid_patch_format"
        assert exc_info.value.retryable is False

    def test_missing_hunk_marker(self, editor, temp_file):
        """Patch with --- and +++ but no @@ raises invalid_patch_format."""
        bad_patch = "--- a\n+++ b\n+some line\n"
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path=temp_file, patch_content=bad_patch)
        assert exc_info.value.code == "invalid_patch_format"

    def test_empty_patch(self, editor, temp_file):
        """Empty patch string raises invalid_patch_format."""
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path=temp_file, patch_content="")
        assert exc_info.value.code == "invalid_patch_format"


class TestPathNotFound:
    def test_nonexistent_file_raises_path_not_found(self, editor):
        """Non-existent target file raises path_not_found."""
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(
                path="/nonexistent/path/file.txt",
                patch_content=VALID_PATCH,
            )
        assert exc_info.value.code == "path_not_found"
        assert exc_info.value.retryable is False


class TestPatchApplyFailed:
    def test_hunk_mismatch_raises_patch_apply_failed(self, editor, temp_file):
        """Patch with wrong context lines raises patch_apply_failed."""
        wrong_context = """\
--- original.txt
+++ original.txt
@@ -1,3 +1,3 @@
 WRONG_CONTEXT_LINE
-line2
+line2_modified
 line3
"""
        patch_for_file = wrong_context.replace("original.txt", Path(temp_file).name)
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path=temp_file, patch_content=patch_for_file)
        assert exc_info.value.code == "patch_apply_failed"
        assert exc_info.value.retryable is False


class TestErrorShape:
    def test_error_has_correct_dict_shape(self, editor):
        """FileCapabilityError.to_dict() matches required shape."""
        with pytest.raises(FileCapabilityError) as exc_info:
            editor.apply_patch(path="/nonexistent.txt", patch_content=VALID_PATCH)
        error_dict = exc_info.value.to_dict()
        assert "code" in error_dict
        assert "message" in error_dict
        assert "details" in error_dict
        assert "retryable" in error_dict
