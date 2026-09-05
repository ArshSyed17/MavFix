"""
MavFix Genesis — Allow-List Loader
Parses config/allow_list.yaml and exposes typed Pydantic models.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class CommandTier(str, Enum):
    AUTO = "auto"
    APPROVAL = "approval"
    BLOCKED = "blocked"


class RemediationCommand(BaseModel):
    """A single entry in the remediation allow-list."""

    name: str = Field(description="Command identifier (key in YAML).")
    tier: CommandTier = Field(description="Risk tier: auto | approval | blocked.")
    description: str = Field(description="Human-readable explanation.")
    tags: list[str] = Field(default_factory=list, description="Applicable scenario tags.")
    timeout_sec: int = Field(default=30, description="Max wall-clock seconds.")
    live_cmd: Optional[str] = Field(
        default=None,
        description="Shell command executed in LIVE_MODE (None = blocked).",
    )

    @model_validator(mode="after")
    def blocked_commands_must_have_no_live_cmd(self) -> "RemediationCommand":
        if self.tier == CommandTier.BLOCKED and self.live_cmd is not None:
            raise ValueError(
                f"Command '{self.name}' is BLOCKED but has a live_cmd set. "
                "Set live_cmd to null for blocked commands."
            )
        return self


class AllowList(BaseModel):
    """The full allow-list, parsed from allow_list.yaml."""

    commands: dict[str, RemediationCommand] = Field(default_factory=dict)

    def get(self, command_name: str) -> Optional[RemediationCommand]:
        return self.commands.get(command_name)

    def tier_of(self, command_name: str) -> CommandTier:
        """Return the tier for a command, defaulting to BLOCKED if unknown."""
        cmd = self.commands.get(command_name)
        return cmd.tier if cmd else CommandTier.BLOCKED

    def commands_for_scenario(self, scenario_tag: str) -> list[RemediationCommand]:
        """Return all commands applicable to a given scenario tag."""
        return [
            cmd for cmd in self.commands.values()
            if scenario_tag in cmd.tags
        ]

    def auto_commands(self) -> list[RemediationCommand]:
        return [c for c in self.commands.values() if c.tier == CommandTier.AUTO]

    def approval_commands(self) -> list[RemediationCommand]:
        return [c for c in self.commands.values() if c.tier == CommandTier.APPROVAL]


@lru_cache(maxsize=1)
def load_allow_list(path: Optional[str] = None) -> AllowList:
    """
    Load and validate the allow-list YAML.
    Cached after first load — restart app to reload changes.
    """
    from config.settings import settings

    yaml_path = Path(path) if path else settings.allow_list_abs_path

    if not yaml_path.exists():
        raise FileNotFoundError(f"Allow-list not found at: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        raw: dict = yaml.safe_load(f)

    commands_raw: dict = raw.get("commands", {})
    commands: dict[str, RemediationCommand] = {}

    for cmd_name, cmd_data in commands_raw.items():
        commands[cmd_name] = RemediationCommand(name=cmd_name, **cmd_data)

    return AllowList(commands=commands)
