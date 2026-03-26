from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src", "tests", "tests_runtime")
DEPRECATED_DATETIME_UTCNOW = "datetime" + ".utcnow("


def test_project_python_files_do_not_use_deprecated_datetime_utcnow():
    violations: list[str] = []

    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            content = path.read_text(encoding="utf-8")
            if DEPRECATED_DATETIME_UTCNOW not in content:
                continue
            relative_path = path.relative_to(PROJECT_ROOT)
            violations.append(str(relative_path))

    assert violations == []
