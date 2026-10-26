"""Pinned source patches are repeatable and invalidate compiled SDK caches."""
import importlib.util
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepare_llvm.py"
spec = importlib.util.spec_from_file_location("prepare_patches", SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def patch_tree(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input").write_text("before\n")
    patches = tmp_path / "patches" / prepare.LLVM_VERSION
    patches.mkdir(parents=True)
    patch = patches / "backend.patch"
    patch.write_text("diff --git a/input b/input\n--- a/input\n+++ b/input\n@@ -1 +1 @@\n-before\n+after\n")
    monkeypatch.setattr(prepare, "PROJECT_ROOT", tmp_path)
    return source, patch


def test_apply_is_idempotent_and_rejects_modified_source(tmp_path, monkeypatch):
    source, patch = patch_tree(tmp_path, monkeypatch)
    prepare.apply_llvm_patches(source)
    assert (source / "input").read_text() == "after\n"
    prepare.apply_llvm_patches(source)
    (source / "input").write_text("unrelated local change\n")
    with pytest.raises(RuntimeError, match="does not match"):
        prepare.apply_llvm_patches(source)
    assert (source / "input").read_text() == "unrelated local change\n"


def test_patch_content_changes_source_and_sdk_cache_identity(tmp_path, monkeypatch):
    source, patch = patch_tree(tmp_path, monkeypatch)
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import prepare_llvm
    monkeypatch.setattr(prepare_llvm, "PROJECT_ROOT", tmp_path)

    def key():
        return runpy.run_path(str(SCRIPT.with_name("cache_key.py")))["key"]

    previous = key()
    source_id = prepare.source_identity("llvm")
    zlib_id = prepare.source_identity("zlib")
    patch.write_text(patch.read_text().replace("+after", "+changed"))
    assert key() != previous
    assert prepare.source_identity("llvm") != source_id
    assert prepare.source_identity("zlib") == zlib_id
