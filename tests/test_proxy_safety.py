"""Guard against restoring blanket retries after write APIs were introduced."""
from pathlib import Path
import re


def test_proxy_does_not_replay_mutating_requests():
    config = (Path(__file__).resolve().parents[1] / "deploy" / "nginx.conf").read_text()
    directives = "\n".join(line.split("#", 1)[0] for line in config.splitlines())
    assert "non_idempotent" not in directives
    write_location = re.search(
        r"location ~ \^/v1/\(documents\|jobs\)\(/\|\$\)\s*\{([^}]+)\}", directives)
    assert write_location
    assert "proxy_next_upstream off;" in write_location.group(1)
