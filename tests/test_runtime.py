import io
import tarfile
import zipfile

import httpx
from papermind.runtime import downloader, llama_bin
from papermind.runtime.catalog import EMBED_MODELS, LLM_MODELS, get_model


def test_catalog_consistent():
    assert {"minicpm5-2b", "qwen3.5-9b", "qwen3.5-4b"} <= set(LLM_MODELS)
    assert get_model("qwen3-embedding-0.6b").query_prefix.startswith("Instruct:")
    assert len({m.path_name for m in [*LLM_MODELS.values(), *EMBED_MODELS.values()]}) == len(LLM_MODELS) + len(
        EMBED_MODELS
    )


def test_release_asset_patterns_cover_platforms(monkeypatch):
    for system, machine, want in [
        ("Windows", "AMD64", "bin-win-cpu-x64"), ("Darwin", "arm64", "bin-macos-arm64"),
        ("Darwin", "x86_64", "bin-macos-x64"), ("Linux", "x86_64", "bin-ubuntu-x64"),
    ]:  # fmt: skip
        monkeypatch.setattr(llama_bin.platform, "system", lambda s=system: s)
        monkeypatch.setattr(llama_bin.platform, "machine", lambda m=machine: m)
        assert llama_bin.release_asset_patterns() == [want]


def test_extract_zip_and_tar(tmp_path):
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("llama-server.exe", b"x")
    llama_bin._extract(z.getvalue(), "a.zip", tmp_path / "z")
    assert (tmp_path / "z" / "llama-server.exe").exists()
    t = io.BytesIO()
    with tarfile.open(fileobj=t, mode="w:gz") as f:
        info = tarfile.TarInfo("llama-b1/llama-server")
        info.size = 1
        f.addfile(info, io.BytesIO(b"x"))
    llama_bin._extract(t.getvalue(), "a.tar.gz", tmp_path / "t")
    assert (tmp_path / "t" / "llama-b1" / "llama-server").exists()


def test_downloader_resume_and_mirror(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 40

    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            return httpx.Response(206, content=payload[start:], headers={"content-length": str(len(payload) - start)})
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    transport = httpx.MockTransport(handler)
    real_stream = httpx.stream

    def fake_stream(method, url, **kw):
        client = httpx.Client(transport=transport)
        return client.stream(method, url, headers=kw.get("headers"))

    monkeypatch.setattr(downloader.httpx, "stream", fake_stream)
    dest = tmp_path / "m.gguf"
    (tmp_path / "m.gguf.part").write_bytes(payload[:1000])  # interrupted earlier
    progress = []
    downloader.download_file("https://hf-mirror.example/x", dest, lambda d, t: progress.append((d, t)))
    assert dest.read_bytes() == payload and progress[-1][0] == len(payload)
    assert downloader.hf_url(get_model("bge-m3"), "https://hf-mirror.com/").startswith(
        "https://hf-mirror.com/ggml-org/"
    )
    monkeypatch.setattr(downloader.httpx, "stream", real_stream)
