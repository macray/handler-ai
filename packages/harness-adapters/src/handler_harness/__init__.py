"""Harness adapters — contract B (docs/dev/contracts.md §B).

Public API:
    catalog.get(name) / catalog.all_harnesses()   load descriptors from harnesses/<name>/
    render(descriptor, agent, scope, secrets)     pure: AgentSpec → HarnessLaunch
    harness_hosts(descriptor, agent, mcp)         pure: the hosts it needs, each with its reason
    images                                        image names, build recipes, version files
"""

from . import catalog, images
from .render import RenderError, harness_hosts, render

__all__ = ["RenderError", "catalog", "harness_hosts", "images", "render"]
