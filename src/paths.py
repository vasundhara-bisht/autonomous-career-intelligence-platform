"""
Central path resolution for the ai-job-agent repository.

All runtime CSV, auth, and state files live under DATA_DIR (default: repo_root/data).
Override with env AI_JOB_AGENT_DATA_DIR for custom layouts.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# src/paths.py -> repository root is one level above src/
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get("AI_JOB_AGENT_DATA_DIR", str(REPO_ROOT / "data"))
).resolve()
CONFIG_DIR = REPO_ROOT / "config"
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
ARCHIVE_DIR = REPO_ROOT / "archive"
LOGS_DIR = REPO_ROOT / "logs"
DIAGRAMS_DIR = REPO_ROOT / "diagrams"
SRC_DIR = REPO_ROOT / "src"
AGENT_DIR = SRC_DIR / "agent"
DASHBOARD_DIR = REPO_ROOT / "dashboard"

_RUNTIME_FILENAMES = (
    "jobs.csv",
    "historical_jobs.csv",
    "job_descriptions.csv",
    "recruiter_crm.csv",
    "job_state.csv",
    "linkedin_auth.json",
    "instahyre_auth.json",
    ".linkedin_query_state.json",
)


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def migrate_legacy_root_runtime_files() -> list[str]:
    """
    One-time move of runtime files from repo root to DATA_DIR if they only exist at root.
    Returns list of migrated filenames.
    """
    ensure_data_dir()
    migrated: list[str] = []
    for name in _RUNTIME_FILENAMES:
        root_path = REPO_ROOT / name
        data_path = DATA_DIR / name
        if root_path.is_file() and not data_path.exists():
            shutil.move(str(root_path), str(data_path))
            migrated.append(name)
    return migrated


def jobs_csv() -> Path:
    return ensure_data_dir() / "jobs.csv"


def historical_jobs_csv() -> Path:
    return ensure_data_dir() / "historical_jobs.csv"


def job_descriptions_csv() -> Path:
    return ensure_data_dir() / "job_descriptions.csv"


def recruiter_crm_csv() -> Path:
    return ensure_data_dir() / "recruiter_crm.csv"


def job_state_csv() -> Path:
    return ensure_data_dir() / "job_state.csv"


def linkedin_auth_json() -> Path:
    return ensure_data_dir() / "linkedin_auth.json"


def instahyre_auth_json() -> Path:
    return ensure_data_dir() / "instahyre_auth.json"


def linkedin_query_state_json() -> Path:
    return ensure_data_dir() / ".linkedin_query_state.json"


def jobs_db() -> Path:
    """
    SQLite product memory database path.

    Default: data/ai_job_agent.db under DATA_DIR.
    Override with AI_JOB_AGENT_DB_PATH (absolute or relative to repo root).
    """
    override = os.environ.get("AI_JOB_AGENT_DB_PATH", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        else:
            path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return ensure_data_dir() / "ai_job_agent.db"


def linkedin_queries_json() -> Path:
    return CONFIG_DIR / "linkedin_queries.json"


def instahyre_feeds_json() -> Path:
    return CONFIG_DIR / "instahyre_feeds.json"


def ai_candidate_profile_path() -> Path:
    """
    Canonical AI scoring candidate profile (markdown).

    Default: config/profiles/ai_candidate_profile.example.md
    Override: AI_CANDIDATE_PROFILE_PATH (absolute or relative to repo root).
    Override with AI_CANDIDATE_PROFILE_PATH for a private resume profile (gitignored).
    """
    override = os.environ.get("AI_CANDIDATE_PROFILE_PATH", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        else:
            path = path.resolve()
        return path
    return (CONFIG_DIR / "profiles" / "ai_candidate_profile.example.md").resolve()


def instahyre_debug_screenshot(label: str) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / label
