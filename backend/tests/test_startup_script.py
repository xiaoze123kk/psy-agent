from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPO_ROOT / "scripts" / "start-local.ps1"
START_AGENT_MILVUS_SCRIPT = REPO_ROOT / "scripts" / "start-agent-milvus.ps1"
START_BACKEND_SCRIPT = REPO_ROOT / "scripts" / "start-backend.ps1"
START_FRONTEND_SCRIPT = REPO_ROOT / "scripts" / "start-frontend.ps1"
START_CMD = REPO_ROOT / "start-local.cmd"


def test_start_local_script_exists_with_expected_entrypoints() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert "DryRun" in script
    assert "start-agent-milvus.ps1" in script
    assert "start-backend.ps1" in script
    assert "start-frontend.ps1" in script
    assert "Start-MilvusWithDockerRun" not in script
    assert "psych-agent-milvus-standalone-live" not in script

    wrapper = START_CMD.read_text(encoding="utf-8")
    assert "scripts\\start-local.ps1" in wrapper


def test_start_agent_milvus_script_uses_agent_compose_and_installs_plugin() -> None:
    script = START_AGENT_MILVUS_SCRIPT.read_text(encoding="utf-8")

    assert 'else { "E:\\milvus-data" }' in script
    assert '$ComposeProject = "agent"' in script
    assert '$EtcdName = "psych-agent-milvus-etcd"' in script
    assert '$MinioName = "psych-agent-milvus-minio"' in script
    assert '$MilvusName = "psych-agent-milvus-standalone"' in script
    assert "Install-DockerComposePlugin" in script
    assert "resources\\cli-plugins\\docker-compose.exe" in script
    assert "docker-compose-windows-x86_64.exe" in script
    assert '"compose", "-p", $ComposeProject, "-f", $ComposeFile' in script
    assert "psych-agent-milvus-standalone-live" not in script
    assert "milvus-data-codex" not in script


def test_start_backend_script_uses_uvicorn_on_backend_port() -> None:
    script = START_BACKEND_SCRIPT.read_text(encoding="utf-8")

    assert "-m\", \"uvicorn\", \"app.main:app\"" in script
    assert "BackendPort = 8000" in script
    assert "uvicorn.local.out.log" in script
    assert "uvicorn.local.err.log" in script
    assert "Test-PortListening" in script


def test_start_frontend_script_uses_vite_on_frontend_port() -> None:
    script = START_FRONTEND_SCRIPT.read_text(encoding="utf-8")

    assert "npm.cmd" in script
    assert "FrontendPort = 5173" in script
    assert "vite.local.out.log" in script
    assert "vite.local.err.log" in script
    assert "--host" in script


def test_start_local_script_dry_run_does_not_start_services() -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        return

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_SCRIPT),
            "-DryRun",
            "-SkipMilvus",
            "-SkipBackend",
            "-SkipFrontend",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "Dry run enabled" in result.stdout
    assert "start-agent-milvus.ps1" not in result.stdout
    assert "Local stack entrypoint is ready" in result.stdout


def test_start_agent_milvus_script_dry_run_shows_agent_compose_command() -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        return

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_AGENT_MILVUS_SCRIPT),
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "docker compose -p agent -f" in result.stdout
    assert "Agent Milvus entrypoint is ready" in result.stdout


def test_start_backend_and_frontend_scripts_dry_run() -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        return

    backend = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_BACKEND_SCRIPT),
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    frontend = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_FRONTEND_SCRIPT),
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )

    assert backend.returncode == 0, backend.stderr
    assert "uvicorn app.main:app" in backend.stdout
    assert "Backend entrypoint is ready" in backend.stdout
    assert frontend.returncode == 0, frontend.stderr
    assert "npm.cmd run dev" in frontend.stdout
    assert "Frontend entrypoint is ready" in frontend.stdout
