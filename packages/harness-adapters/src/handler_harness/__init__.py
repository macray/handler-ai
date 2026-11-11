"""Harness adapters — contract B.

Public API:
    catalog.get(name) / catalog.all_harnesses()   load descriptors from harnesses/<name>/
    render(descriptor, agent, secrets)            pure: AgentSpec → HarnessLaunch
    harness_hosts(descriptor, agent, mcp)         pure: the hosts it needs, each with its reason
    starting_instructions(instructions, network)  pure: what the agent is told before its turn
    images                                        image names, build recipes, version files
"""

from . import catalog, images
from .render import RenderError, harness_hosts, render, starting_instructions

__all__ = ["RenderError", "catalog", "harness_hosts", "images", "render", "starting_instructions"]
