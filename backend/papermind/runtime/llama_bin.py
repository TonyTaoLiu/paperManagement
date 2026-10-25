"""Obtain a `llama-server` binary: release download -> source build -> manual path."""

from __future__ import annotations

import io
import json
import platform
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from papermind.config import data_dir, load_settings

LLAMA_CPP_TAG = "b11721"  # pinned; must support all candidate model architectures
REPO_URL = "https://github.com/ggml-org/llama.cpp"
EXE = "llama-server.exe" if platform.system() == "Windows" else "llama-server"

Log = Callable[[str], None]


class LlamaServerUnavailable(RuntimeError):
    pass


def bin_dir() -> Path:
    p = data_dir() / "bin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_existing() -> Path | None:
    configured = load_settings().get("llama_server_path", "")
    if configured and Path(configured).is_file():
        return Path(configured)
    for p in bin_dir().rglob(EXE):
        if p.is_file():
            return p
    on_path = shutil.which("llama-server")
    return Path(on_path) if on_path else None


def release_asset_patterns() -> list[str]:
    """Substrings that identify the right pre-built asset for this machine."""
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Windows":
        return ["bin-win-cpu-arm64"] if arm else ["bin-win-cpu-x64"]
    if system == "Darwin":
        return ["bin-macos-arm64"] if arm else ["bin-macos-x64"]
    return ["bin-ubuntu-arm64"] if arm else ["bin-ubuntu-x64"]


def _extract(data: bytes, name: str, dest: Path) -> None:
    if name.endswith(".zip"):
        zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            try:
                tf.extractall(dest, filter="data")
            except tarfile.TarError:  # release archives contain relative symlinks for shared libraries
                tf.extractall(dest, filter="tar")


def download_release(log: Log = print) -> Path:
    api = f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{LLAMA_CPP_TAG}"
    r = httpx.get(api, timeout=30, follow_redirects=True)
    r.raise_for_status()
    assets = r.json()["assets"]
    wanted = release_asset_patterns()
    asset = next(
        (a for a in assets if any(w in a["name"] for w in wanted) and "cudart" not in a["name"]),
        None,
    )
    if asset is None:
        raise LlamaServerUnavailable(f"no prebuilt asset for {platform.system()} {wanted}")
    log(f"downloading {asset['name']} ...")
    blob = httpx.get(asset["browser_download_url"], timeout=600, follow_redirects=True)
    blob.raise_for_status()
    dest = bin_dir() / LLAMA_CPP_TAG
    dest.mkdir(parents=True, exist_ok=True)
    _extract(blob.content, asset["name"], dest)
    found = next((p for p in dest.rglob(EXE)), None)
    if found is None:
        raise LlamaServerUnavailable("archive did not contain llama-server")
    found.chmod(0o755)
    return found


def build_from_source(log: Log = print) -> Path:
    for tool in ("git", "cmake"):
        if not shutil.which(tool):
            raise LlamaServerUnavailable(f"{tool} not found; cannot build llama.cpp from source")
    src = data_dir() / "build" / "llama.cpp"
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        log(f"cloning llama.cpp {LLAMA_CPP_TAG} ...")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", LLAMA_CPP_TAG, REPO_URL, str(src)],
            check=True,
        )
    flags = ["-DCMAKE_BUILD_TYPE=Release", "-DLLAMA_CURL=OFF", "-DLLAMA_BUILD_TESTS=OFF"]
    # portable build: pick the best CPU kernels at runtime instead of -march=native
    flags += ["-DLLAMA_BUILD_EXAMPLES=OFF", "-DGGML_NATIVE=OFF", "-DGGML_BACKEND_DL=ON", "-DGGML_CPU_ALL_VARIANTS=ON"]
    log("configuring ...")
    subprocess.run(["cmake", "-S", str(src), "-B", str(src / "build"), *flags], check=True)
    log("building llama-server (several minutes) ...")
    subprocess.run(
        [
            "cmake",
            "--build",
            str(src / "build"),
            "--target",
            "llama-server",
            "--config",
            "Release",
            "-j",
            "4",
        ],
        check=True,
    )
    built = next((p for p in (src / "build").rglob(EXE) if p.is_file()), None)
    if built is None:
        raise LlamaServerUnavailable("build finished but llama-server not found")
    out = bin_dir() / LLAMA_CPP_TAG
    out.mkdir(parents=True, exist_ok=True)
    target = out / EXE
    shutil.copy2(built, target)
    # shared libraries produced next to the binary (ggml/llama) are needed at runtime
    for lib in built.parent.glob("*.so*"):
        shutil.copy2(lib, out / lib.name)
    for lib in built.parent.glob("*.dylib"):
        shutil.copy2(lib, out / lib.name)
    for lib in built.parent.glob("*.dll"):
        shutil.copy2(lib, out / lib.name)
    return target


def ensure_llama_server(log: Log = print) -> Path:
    existing = find_existing()
    if existing:
        return existing
    errors: list[str] = []
    for step in (download_release, build_from_source):
        try:
            return step(log)
        except (httpx.HTTPError, subprocess.CalledProcessError, LlamaServerUnavailable) as e:
            errors.append(f"{step.__name__}: {e}")
            log(f"{step.__name__} failed: {e}")
    raise LlamaServerUnavailable(
        "Could not obtain llama-server automatically ("
        + json.dumps(errors, ensure_ascii=False)
        + "). Install llama.cpp yourself and set its path in Settings."
    )
