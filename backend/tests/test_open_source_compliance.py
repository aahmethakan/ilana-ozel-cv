from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def test_release_materials_include_unmodified_agpl_text_and_project_notices() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (PROJECT_ROOT / "NOTICE").read_text(encoding="utf-8")
    third_party = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert license_text.startswith("                    GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert "Ilana Ozel CV" in notice and "AHA" in notice
    for dependency in ("FastAPI", "Uvicorn", "Pydantic", "PyMuPDF", "python-multipart", "OpenAI Python SDK", "python-docx", "pytest", "httpx"):
        assert dependency in third_party


def test_release_ignore_rules_exclude_private_runtime_and_environment_artifacts() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    for rule in (".env", ".venv/", "*.sqlite", "*.sqlite3", "*.db", "*.log", "test_data/manuel/", "backend/generated/", "frontend/generated/"):
        assert rule in gitignore
