from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_cd_examples_exist_and_parse() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    github_workflow = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "reins-pipeline.yml").read_text(encoding="utf-8")
    )
    gitlab_workflow = yaml.safe_load(
        (repo_root / ".gitlab-ci.yml.example").read_text(encoding="utf-8")
    )
    compose = yaml.safe_load(
        (repo_root / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    )

    assert "jobs" in github_workflow
    assert "run-pipeline" in github_workflow["jobs"]
    assert "stages" in gitlab_workflow
    assert "services" in compose
    assert "reins-pipeline" in compose["services"]


def test_ci_cd_docs_and_examples_reference_standalone_runner() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    docs = (repo_root / "docs" / "ci-cd-integration.md").read_text(encoding="utf-8")
    jenkinsfile = (repo_root / "Jenkinsfile.example").read_text(encoding="utf-8")
    dockerfile = (repo_root / "docker" / "Dockerfile.pipeline").read_text(encoding="utf-8")

    assert "scripts/run_pipeline.py" in docs
    assert "scripts/run_pipeline.py" in jenkinsfile
    assert 'ENTRYPOINT ["python3", "scripts/run_pipeline.py"]' in dockerfile
