"""scripts/set-api-key.sh, run only inside temporary directories (never on a real .env)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
# Built by concatenation so a repository-wide search for the real key prefix stays empty.
FAKE = "sk-" + "ant-" + "TESTONLY-0123456789"


def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "set-api-key.sh", tmp_path / "scripts" / "set-api-key.sh")
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    return tmp_path


def run(box: Path, key: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(box / "scripts" / "set-api-key.sh")], input=key + "\n",
                          capture_output=True, text=True, timeout=30)


def key_lines(env: Path) -> list[str]:
    return [line for line in env.read_text().splitlines() if line.startswith("GETNET_ANTHROPIC_API_KEY=")]


def test_creates_env_from_example_and_never_prints_the_key(tmp_path):
    box = sandbox(tmp_path)
    result = run(box, FAKE)
    assert result.returncode == 0, result.stderr
    assert FAKE not in result.stdout + result.stderr
    env = box / ".env"
    assert key_lines(env) == [f"GETNET_ANTHROPIC_API_KEY={FAKE}"]
    example_rest = [l for l in (box / ".env.example").read_text().splitlines() if not l.startswith("GETNET_ANTHROPIC_API_KEY=")]
    assert [l for l in env.read_text().splitlines() if not l.startswith("GETNET_ANTHROPIC_API_KEY=")] == example_rest
    assert oct(env.stat().st_mode & 0o777) == "0o600"


def test_replaces_only_the_key_line_in_an_existing_env(tmp_path):
    box = sandbox(tmp_path)
    (box / ".env").write_text("OPERATOR_API_KEY=keep-me\nGETNET_ANTHROPIC_API_KEY=old\nLOG_LEVEL=DEBUG\n")
    assert run(box, FAKE).returncode == 0
    assert (box / ".env").read_text() == f"OPERATOR_API_KEY=keep-me\nGETNET_ANTHROPIC_API_KEY={FAKE}\nLOG_LEVEL=DEBUG\n"


def test_appends_the_key_when_missing_even_without_trailing_newline(tmp_path):
    box = sandbox(tmp_path)
    (box / ".env").write_text("LOG_LEVEL=INFO")
    assert run(box, FAKE).returncode == 0
    assert (box / ".env").read_text() == f"LOG_LEVEL=INFO\nGETNET_ANTHROPIC_API_KEY={FAKE}\n"


@pytest.mark.parametrize("bad", ["", "not-a-key", "sk-other-123"])
def test_rejects_keys_without_the_expected_prefix_and_writes_nothing(tmp_path, bad):
    box = sandbox(tmp_path)
    (box / ".env").write_text("LOG_LEVEL=INFO\n")
    result = run(box, bad)
    assert result.returncode == 1
    assert (box / ".env").read_text() == "LOG_LEVEL=INFO\n"
    assert [p.name for p in box.glob(".env.*") if p.name != ".env.example"] == []  # no temp file left
