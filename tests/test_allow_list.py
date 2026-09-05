"""
MavFix Genesis — Allow-List Tests
"""

import pytest
from config.loader import CommandTier, load_allow_list


def test_load_allow_list():
    al = load_allow_list()
    assert len(al.commands) > 0
    assert "restart_pod" in al.commands
    assert "rollback_deployment" in al.commands
    assert "delete_persistent_volume" in al.commands


def test_command_tiers():
    al = load_allow_list()
    assert al.tier_of("restart_pod") == CommandTier.AUTO
    assert al.tier_of("scale_replicas") == CommandTier.AUTO
    assert al.tier_of("rollback_deployment") == CommandTier.APPROVAL
    assert al.tier_of("delete_persistent_volume") == CommandTier.BLOCKED
    assert al.tier_of("unknown_command_xyz") == CommandTier.BLOCKED


def test_auto_and_approval_lists():
    al = load_allow_list()
    autos = al.auto_commands()
    approvals = al.approval_commands()
    assert len(autos) >= 5
    assert len(approvals) >= 3
    assert all(c.tier == CommandTier.AUTO for c in autos)
    assert all(c.tier == CommandTier.APPROVAL for c in approvals)
