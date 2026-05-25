from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPO_ROOT / "scripts" / "start-local.ps1"
START_AGENT_MILVUS_SCRIPT = REPO_ROOT / "scripts" / "start-agent-milvus.ps1"
START_BACKEND_SCRIPT = REPO_ROOT / "scripts" / "start-backend.ps1"
START_FRONTEND_SCRIPT = REPO_ROOT / "scripts" / "start-frontend.ps1"
LIVE_SMOKE_SCRIPT = REPO_ROOT / "scripts" / "live-smoke.ps1"
BACKEND_LIVE_SMOKE_SCRIPT = REPO_ROOT / "backend" / "scripts" / "live_smoke.py"
BACKEND_RAG_READY_SCRIPT = REPO_ROOT / "backend" / "scripts" / "check_rag_ready.py"
START_CMD = REPO_ROOT / "start-local.cmd"
LIVE_SMOKE_CMD = REPO_ROOT / "live-smoke.cmd"
BACKEND_ENV_EXAMPLE = REPO_ROOT / "backend" / ".env.example"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def test_start_local_script_exists_with_expected_entrypoints() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert "DryRun" in script
    assert "start-agent-milvus.ps1" in script
    assert "start-backend.ps1" in script
    assert "start-frontend.ps1" in script
    assert "Assert-RagReady" in script
    assert "check_rag_ready.py" in script
    assert "Write-SearchPreflight" in script
    assert "Start-MilvusWithDockerRun" not in script
    assert "psych-agent-milvus-standalone-live" not in script

    wrapper = START_CMD.read_text(encoding="utf-8")
    assert "scripts\\start-local.ps1" in wrapper


def test_live_smoke_entrypoint_exists_with_expected_queries_and_diagnostics() -> None:
    script = LIVE_SMOKE_SCRIPT.read_text(encoding="utf-8")
    backend_script = BACKEND_LIVE_SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "start-local.ps1" in script
    assert "live_smoke.py" in script
    assert "SkipStart" in script
    assert "DryRun" in script
    assert "张雪峰去世时间是什么？" in backend_script
    assert "特朗普访华是什么时候？" in backend_script
    assert "2026年3月24日15时50分" in backend_script
    assert "2026年5月13日至15日" in backend_script
    assert "provider" in backend_script
    assert "prefetch" in backend_script
    assert "fallback" in backend_script

    wrapper = LIVE_SMOKE_CMD.read_text(encoding="utf-8")
    assert "scripts\\live-smoke.ps1" in wrapper


def test_backend_env_example_documents_search_provider_chain() -> None:
    env_example = BACKEND_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "SEARCH_PROVIDER=bing_web" in env_example
    assert "BING_SEARCH_API_KEY=" in env_example
    assert "BING_SEARCH_ENDPOINT=https://api.bing.microsoft.com/v7.0/search" in env_example
    assert "SEARCH_PROXY=" in env_example


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
    assert "[switch]$Reload" in script
    assert "$args += \"--reload\"" in script
    assert "LOCAL_EMBEDDING_USE_WORKER" in script
    assert "RAG_RETRIEVAL_TIMEOUT_SECONDS" in script
    assert "EMBEDDING_TIMEOUT_SECONDS" in script
    assert "uvicorn.local.out.log" in script
    assert "uvicorn.local.err.log" in script
    assert "Test-PortListening" in script


def test_backend_rag_ready_script_checks_milvus_embedding_and_retrieval() -> None:
    script = BACKEND_RAG_READY_SCRIPT.read_text(encoding="utf-8")

    assert "milvus_store.is_available" in script
    assert "embedding_client.embed_query" in script
    assert "retrieve_counseling_examples_with_trace" in script
    assert "rag_ready" in script
    assert "milvus_unavailable" in script
    assert "embedding_unavailable" in script


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

    env = os.environ.copy()
    env["SEARCH_PROVIDER"] = "bing_web"
    env["BING_SEARCH_API_KEY"] = ""
    env["BING_SEARCH_ENDPOINT"] = "https://api.bing.microsoft.com/v7.0/search"

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
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "Dry run enabled" in result.stdout
    assert "Search preflight" in result.stdout
    assert "SEARCH_PROVIDER=bing_web" in result.stdout
    assert "BING_SEARCH_API_KEY configured: no" in result.stdout
    assert "Chinese fallback chain: bing_web -> sogou_web -> baidu_mobile -> ddg" in result.stdout
    assert "Fallback to Sogou: yes; Baidu: yes; DDG: yes" in result.stdout
    assert "start-agent-milvus.ps1" not in result.stdout
    assert "Skipping RAG readiness check" in result.stdout
    assert "Local stack entrypoint is ready" in result.stdout


def test_live_smoke_script_dry_run_does_not_start_services_or_query() -> None:
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
            str(LIVE_SMOKE_SCRIPT),
            "-DryRun",
            "-SkipStart",
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
    assert "Skipping local stack startup" in result.stdout
    assert "Would run backend live smoke" in result.stdout
    assert "张雪峰去世时间是什么？" in result.stdout
    assert "特朗普访华是什么时候？" in result.stdout


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
    assert "--reload" not in backend.stdout
    assert "LOCAL_EMBEDDING_USE_WORKER=1" in backend.stdout
    assert "Backend entrypoint is ready" in backend.stdout
    assert frontend.returncode == 0, frontend.stderr
    assert "npm.cmd run dev" in frontend.stdout
    assert "Frontend entrypoint is ready" in frontend.stdout


def test_agents_documents_full_stack_startup_script_and_rag_checks() -> None:
    agents = AGENTS_MD.read_text(encoding="utf-8")

    assert "scripts/start-local.ps1" in agents
    assert "start-local.cmd" in agents
    assert "scripts/start-agent-milvus.ps1" in agents
    assert "scripts/start-backend.ps1" in agents
    assert "scripts/start-frontend.ps1" in agents
    assert "backend/scripts/check_rag_ready.py" in agents
    assert "RAG" in agents
    assert "无 `--reload`" in agents
