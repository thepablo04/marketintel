"""Validate the shared frontend before Vercel publishes its canonical assets."""

from pathlib import Path


def runtime_dependencies(path):
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def main():
    root = Path(__file__).resolve().parent.parent
    if runtime_dependencies(root / "requirements.txt") != runtime_dependencies(
        root / "MarketIntel-v6.4" / "requirements.txt"
    ):
        raise RuntimeError("Local and Vercel runtime dependencies must match.")
    source = root / "MarketIntel-v6.4" / "static"
    if not source.is_dir():
        raise RuntimeError(f"Missing frontend assets: {source}")
    # Vercel collects public files before the Flask build command. The checked-in
    # public/static link makes the same assets available at collection time.
    public = root / "public" / "static"
    assets = [path for path in source.rglob("*") if path.is_file()]
    for path in assets:
        published = public / path.relative_to(source)
        if not published.is_file() or published.read_bytes() != path.read_bytes():
            raise RuntimeError(f"Missing or outdated CDN asset: {published}")
    for public_path, source_path in (
        (root / "public/frangi/index.html", root / "Frangi/frangi.html"),
        (root / "public/frangi/bridge.html", root / "Frangi/bridge.html"),
    ):
        if not public_path.is_file() or public_path.read_bytes() != source_path.read_bytes():
            raise RuntimeError(f"Missing or outdated Frangi asset: {public_path}")
    import zipfile
    bundle = root / "public/descargas/Frangi-sincronizado.zip"
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None or archive.read("frangi.html") != (root / "Frangi/frangi.html").read_bytes():
            raise RuntimeError("The Frangi download does not match the published calendar.")
    print(f"Validated {len(assets)} shared static assets.")


if __name__ == "__main__":
    main()
