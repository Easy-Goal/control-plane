"""Leitor de TOML: o da stdlib (3.11+) ou o tomli empacotado (MIT, mesmo código), para rodar também no Python 3.9."""
try:
    import tomllib
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "_vendor"))
    import tomli as tomllib  # noqa: F401
