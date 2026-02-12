"""Tests for pam.common.utils."""

from pam.common.utils import escape_like


class TestEscapeLike:
    def test_no_wildcards(self):
        assert escape_like("hello world") == "hello world"

    def test_escapes_percent(self):
        assert escape_like("100%") == "100\\%"

    def test_escapes_underscore(self):
        assert escape_like("file_name") == "file\\_name"

    def test_escapes_backslash(self):
        assert escape_like("path\\to") == "path\\\\to"

    def test_escapes_all_wildcards(self):
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_empty_string(self):
        assert escape_like("") == ""

    def test_multiple_wildcards(self):
        assert escape_like("a%b%c_d") == "a\\%b\\%c\\_d"
