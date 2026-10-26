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
    (source / "input").write_text("before\n", newline="\n")
    patches = tmp_path / "patches" / prepare.LLVM_VERSION
    patches.mkdir(parents=True)
    patch = patches / "backend.patch"
    patch.write_text("diff --git a/input b/input\n--- a/input\n+++ b/input\n@@ -1 +1 @@\n-before\n+after\n", newline="\n")
    monkeypatch.setattr(prepare, "PROJECT_ROOT", tmp_path)
    return source, patch


def test_apply_is_idempotent_and_rejects_modified_source(tmp_path, monkeypatch):
    source, patch = patch_tree(tmp_path, monkeypatch)
    prepare.apply_llvm_patches(source)
    assert (source / "input").read_text() == "after\n"
    prepare.apply_llvm_patches(source)
    (source / "input").write_text("unrelated local change\n", newline="\n")
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
    patch.write_text(patch.read_text().replace("+after", "+changed"), newline="\n")
    assert key() != previous
    assert prepare.source_identity("llvm") != source_id
    assert prepare.source_identity("zlib") == zlib_id


def test_downloaded_tree_is_reextracted_when_patch_changes(tmp_path, monkeypatch):
    import hashlib
    import io
    import tarfile

    _, patch = patch_tree(tmp_path, monkeypatch)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        content = b"before\n"
        entry = tarfile.TarInfo("llvm-source/input")
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))
    data = payload.getvalue()
    monkeypatch.setattr(prepare, "SOURCES", {"llvm": {
        "version": prepare.LLVM_VERSION, "url": "https://example.org/llvm.tar.gz",
        "sha256": hashlib.sha256(data).hexdigest()}})
    calls = []

    def download(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(data)

    monkeypatch.setattr(prepare.urllib.request, "urlopen", download)
    work = tmp_path / "work"
    first = prepare.source_tree("llvm", work)
    assert (first / "input").read_text() == "after\n"
    patch.write_text(patch.read_text().replace("+after", "+changed"), newline="\n")
    second = prepare.source_tree("llvm", work)
    assert second == first
    assert (second / "input").read_text() == "changed\n"
    assert len(calls) == 1
