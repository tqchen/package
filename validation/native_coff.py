"""Build the patched JITLink archive and validate it in a released native SDK."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "packages/mlc-llvm-static/scripts"))
import prepare_llvm


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


work = root / "native-build"
source = prepare_llvm.source_tree("llvm", work)
build = work / "llvm"
run("cmake", "-S", source / "llvm", "-B", build, "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl",
    "-DLLVM_TARGETS_TO_BUILD=AArch64", "-DLLVM_INCLUDE_TESTS=OFF",
    "-DLLVM_INCLUDE_BENCHMARKS=OFF", "-DLLVM_ENABLE_ASSERTIONS=OFF",
    "-DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF", "-DLLVM_ENABLE_RTTI=OFF", "-DLLVM_ENABLE_EH=OFF",
    "-DLLVM_USE_CRT_RELEASE=MD", "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL",
    "-DLLVM_ENABLE_ZLIB=OFF", "-DLLVM_ENABLE_ZSTD=OFF", "-DLLVM_ENABLE_LIBXML2=OFF",
    "-DLLVM_ENABLE_LIBEDIT=OFF", "-DLLVM_ENABLE_Z3_SOLVER=OFF", "-DLLVM_ENABLE_DIA_SDK=OFF")
run("cmake", "--build", build, "--target", "LLVMJITLink", "llvm-jitlink", "llvm-mc", "--parallel", "8")
sdk = Path(subprocess.check_output([sys.executable, "-m", "mlc_llvm_static.config", "--prefix"], text=True).strip())
archive = sdk / "lib/LLVMJITLink.lib"
original = hashlib.sha256(archive.read_bytes()).hexdigest()
shutil.copy2(build / "lib/LLVMJITLink.lib", archive)
for header in ("COFF_aarch64.h", "aarch64.h"):
    shutil.copy2(source / "llvm/include/llvm/ExecutionEngine/JITLink" / header,
                 sdk / "include/llvm/ExecutionEngine/JITLink" / header)
fixture = source / "llvm/test/ExecutionEngine/JITLink/AArch64/COFF_relocations.s"
obj = work / "coff_reloc.o"
run(build / "bin/llvm-mc.exe", "-triple=aarch64-pc-windows-msvc", "-filetype=obj", "-o", obj, fixture)
run(build / "bin/llvm-jitlink.exe", "-noexec", "-slab-allocate", "100Kb", "-slab-address", "0x10000000",
    "-slab-page-size", "4096", "-abs", "__ImageBase=0x10000000", "-abs", "external_func=0x7000000000",
    "-abs", "external_data=0x12345008", "-check", fixture, obj)
evidence = {"llvm_version": prepare_llvm.LLVM_VERSION, "source_sha256": prepare_llvm.SOURCES["llvm"]["sha256"],
            "patches": prepare_llvm.patch_identity(), "base_sdk_jitlink_sha256": original,
            "patched_jitlink_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "package_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "consumer_head": subprocess.check_output(["git", "-C", "consumer", "rev-parse", "HEAD"], text=True).strip(),
            "validation_mode": "Complete JITLink archive built from patched source; other SDK archives are released23.1.1.post0"}
(root / "native-evidence.json").write_text(json.dumps(evidence, indent=2))
shutil.make_archive(str(root / "patched-sdk"), "zip", sdk)
