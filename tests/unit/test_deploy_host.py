"""Exercise deployment ordering and rollback without touching Docker or production."""

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy_host.sh"
SHA = "a" * 40


@pytest.mark.parametrize("failure", ["", "build", "health"])
def test_deploy_preserves_service_on_failure(tmp_path, failure):
    root = tmp_path / "app"
    (root / "releases").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = tmp_path / "commands"
    docker = bin_dir / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s %s\\n' "${LANDSCAPES_IMAGE:-}" "$*" >> "$COMMAND_LOG"
case "$1" in
  build) [[ "$FAILURE" != build ]] ;;
  inspect) echo lost-landscapes:previous ;;
  compose) exit 0 ;;
esac
''')
    curl = bin_dir / "curl"
    curl.write_text('#!/usr/bin/env bash\n[[ "$FAILURE" != health ]]\n')
    docker.chmod(0o700)
    curl.chmod(0o700)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name in ("Dockerfile.cpu", "compose.cpu.yml"):
            entry = tarfile.TarInfo(name)
            entry.size = 0
            tar.addfile(entry, io.BytesIO())
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LANDSCAPES_DEPLOY_ROOT": str(root),
        "SSH_ORIGINAL_COMMAND": SHA,
        "COMMAND_LOG": str(commands),
        "FAILURE": failure,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], input=archive.getvalue(), env=env,
        capture_output=True, timeout=10,
    )
    log = commands.read_text()
    if failure:
        assert result.returncode != 0
        assert not (root / "deployed-commit").exists()
        if failure == "build":
            assert "compose" not in log  # Existing service is never touched.
        else:
            assert "lost-landscapes:previous compose" in log
            assert log.index(f"lost-landscapes:{SHA} compose") < log.index("lost-landscapes:previous compose")
    else:
        assert result.returncode == 0, result.stderr.decode()
        assert (root / "deployed-commit").read_text().strip() == SHA
        assert log.index("build") < log.index("compose")
        assert "lost-landscapes:previous compose" not in log
