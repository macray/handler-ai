"""Control plane — the only block that composes the others (code map).

Composition (M2): model access (E), secrets, compose (B → A), sandbox_process, agent.
Daemon (M3): settings, auth, agents, policy (C.4), relay (C transport), api (D + C), daemon.
"""

__version__ = "0.3.1"
