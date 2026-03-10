"""Tests for brain_sync.fs_utils."""

from pathlib import Path

import pytest

from brain_sync.fs_utils import normalize_path

pytestmark = pytest.mark.unit


def test_normalize_path_dot_path_returns_empty():
    assert normalize_path(Path(".")) == ""


def test_normalize_path_dot_string_returns_empty():
    assert normalize_path(".") == ""


def test_normalize_path_backslashes():
    assert normalize_path("foo\\bar\\baz") == "foo/bar/baz"


def test_normalize_path_normal():
    assert normalize_path("foo/bar") == "foo/bar"


def test_normalize_path_empty_string():
    assert normalize_path("") == ""
