"""Server startup configuration.

See docs/designs/echo-memory-design.md's "Configuration" section: group_id is
never typed or constructed by the calling agent, it's resolved server-side
from these values plus the scope ("solo" | "shared") passed on each call.
"""

import os
from dataclasses import dataclass

from echo_memory.infra.project import UNKNOWN, detect_project


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    user_id: str
    agent_id: str
    database_url: str
    # Which project this process is writing from. Resolved from cwd, never
    # passed by the calling agent (see infra/project.py). Defaults to
    # "unknown" so a Config built by hand - tests, embedders - stays valid.
    project: str = UNKNOWN

    def solo_group_id(self) -> str:
        return f"user:{self.user_id}:agent:{self.agent_id}"

    def shared_group_id(self) -> str:
        return f"user:{self.user_id}:shared"

    def group_id(self, scope: str) -> str:
        if scope == "solo":
            return self.solo_group_id()
        if scope == "shared":
            return self.shared_group_id()
        raise ConfigError(f'scope must be "solo" or "shared", got {scope!r}')


def load_config(env: dict | None = None) -> Config:
    env = env if env is not None else os.environ
    missing = [
        name
        for name in ("ECHO_MEMORY_USER_ID", "ECHO_MEMORY_AGENT_ID", "ECHO_MEMORY_DATABASE_URL")
        if not env.get(name)
    ]
    if missing:
        raise ConfigError(f"missing required environment variable(s): {', '.join(missing)}")
    return Config(
        user_id=env["ECHO_MEMORY_USER_ID"],
        agent_id=env["ECHO_MEMORY_AGENT_ID"],
        database_url=env["ECHO_MEMORY_DATABASE_URL"],
        project=detect_project(env=env),
    )
