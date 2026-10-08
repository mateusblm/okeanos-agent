"""The AFK runner (skills/engineering/afk/scaffold/main.mts) against the real Sandcastle.

Installs the scaffold's dependencies once into a cached temp dir, then:
- typechecks main.mts with strict TypeScript;
- runs it with each supported AGENT and checks it gets past the agent check;
- runs it with an unsupported AGENT and checks it fails at startup listing
  the supported agents.

Skipped when node/npm are missing or OKEANOS_SKIP_SLOW is set.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCAFFOLD = REPO / "skills" / "engineering" / "afk" / "scaffold"
SUPPORTED = ["claude", "codex", "copilot", "cursor"]

pytestmark = [
    pytest.mark.skipif(bool(os.environ.get("OKEANOS_SKIP_SLOW")), reason="OKEANOS_SKIP_SLOW set"),
    pytest.mark.skipif(
        not (shutil.which("node") and shutil.which("npm")), reason="node/npm unavailable"
    ),
]


@pytest.fixture(scope="module")
def runner_dir() -> Path:
    """A cached install of the scaffold's package.json plus typescript."""
    package_json = (SCAFFOLD / "package.json").read_text()
    key = hashlib.sha256(package_json.encode()).hexdigest()[:12]
    cache = Path(tempfile.gettempdir()) / f"okeanos-afk-runner-{key}"
    marker = cache / "node_modules" / "@ai-hero" / "sandcastle" / "package.json"
    tsc = cache / "node_modules" / ".bin" / "tsc"
    if not (marker.exists() and tsc.exists()):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "package.json").write_text(package_json)
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--silent"],
            cwd=cache, check=True, timeout=600,
        )
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--silent", "--no-save",
             "typescript@^5", "@types/node@^22"],
            cwd=cache, check=True, timeout=600,
        )
    return cache


def with_agent(source: str, agent: str) -> str:
    patched, count = re.subn(
        r'^const AGENT(?:: string)? = "[^"]*";', f'const AGENT: string = "{agent}";',
        source, flags=re.M,
    )
    assert count == 1, "main.mts must declare `const AGENT = \"...\";` exactly once"
    return patched


def test_main_typechecks_strict(runner_dir: Path):
    shutil.copy(SCAFFOLD / "main.mts", runner_dir / "main.mts")
    result = subprocess.run(
        [str(runner_dir / "node_modules" / ".bin" / "tsc"), "--noEmit", "--strict",
         "--module", "nodenext", "--moduleResolution", "nodenext", "--target", "es2022",
         "--skipLibCheck", "--types", "node", "main.mts"],
        cwd=runner_dir, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_with_agent(runner_dir: Path, agent: str) -> subprocess.CompletedProcess:
    script = runner_dir / f"main-{agent}.mts"
    script.write_text(with_agent((SCAFFOLD / "main.mts").read_text(), agent))
    # No feature argument: a runner that passes the agent check stops at usage.
    return subprocess.run(
        [str(runner_dir / "node_modules" / ".bin" / "tsx"), str(script)],
        cwd=runner_dir, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("agent", SUPPORTED)
def test_supported_agent_passes_startup_check(runner_dir: Path, agent: str):
    result = run_with_agent(runner_dir, agent)
    assert result.returncode != 0
    assert "Usage:" in result.stderr, result.stderr
    assert "Unsupported AGENT" not in result.stderr


def test_unsupported_agent_fails_listing_supported(runner_dir: Path):
    result = run_with_agent(runner_dir, "gemini")
    assert result.returncode != 0
    assert "Unsupported AGENT" in result.stderr, result.stderr
    assert "gemini" in result.stderr
    for agent in SUPPORTED:
        assert agent in result.stderr
    assert "Usage:" not in result.stderr
