"""Project detection: resolved from cwd, never from the calling agent.
See src/echo_memory/infra/project.py."""

import subprocess

from echo_memory.infra.project import UNKNOWN, detect_project, normalize


def test_normalize_keeps_ordinary_repo_names():
    assert normalize("echo-mem") == "echo-mem"
    assert normalize("ayush_trade.bot") == "ayush_trade.bot"


def test_normalize_replaces_unsafe_characters():
    assert normalize("my project/v2") == "my-project-v2"
    assert normalize("  spaced  ") == "spaced"


def test_normalize_falls_back_rather_than_returning_empty():
    assert normalize("///") == UNKNOWN
    assert normalize("") == UNKNOWN


def test_normalize_caps_length():
    assert len(normalize("x" * 200)) == 64


def test_env_override_wins_over_cwd(tmp_path):
    assert detect_project(str(tmp_path), env={"ECHO_MEMORY_PROJECT": "embedded-svc"}) == "embedded-svc"


def test_override_is_normalized_like_any_other_name(tmp_path):
    assert detect_project(str(tmp_path), env={"ECHO_MEMORY_PROJECT": "Some Service"}) == "Some-Service"


def test_plain_directory_uses_its_own_name(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert detect_project(str(plain), env={}) == "not-a-repo"


def test_a_subdirectory_of_a_repo_reports_the_repo(tmp_path):
    repo = tmp_path / "my-repo"
    (repo / "src" / "deep").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    assert detect_project(str(repo / "src" / "deep"), env={}) == "my-repo"
