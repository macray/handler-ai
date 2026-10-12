"""What an agent runs as (contract E): a harness, the account (accounts.py) or the provider
(providers.py) its model calls use, and a model. `resolve` turns an agent's names into the
`AgentSpec` render takes (B.3), checked (E1): the harness exists, the account is its own and the
provider speaks a protocol it accepts and serves the model.
"""

from handler_contracts import AgentSpec
from handler_harness import catalog

from . import accounts, providers
from .settings import Sources


def account_harness(sources: Sources, account: str) -> str:
    """The harness an account was made for; ValueError when it is missing or invalid."""
    loaded = accounts.get(sources.accounts, account)
    if loaded.account is None:
        raise ValueError(f"account '{account}': {loaded.error}")
    return loaded.account.harness


def resolve(
    sources: Sources,
    harness: str,
    *,
    account: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AgentSpec:
    """The agent's harness with its account or provider, resolved; ValueError when one is
    unusable (E1)."""
    try:
        descriptor = catalog.get(harness).descriptor
    except catalog.UnknownHarnessError as e:
        raise ValueError(str(e)) from None
    if account is not None:
        loaded = accounts.get(sources.accounts, account)
        if loaded.account is None:
            raise ValueError(f"account '{account}': {loaded.error}")
        spec = AgentSpec.resolve(harness, model, account=(account, loaded.account))
        login = descriptor.login
        if login and login.file and sources.credentials is not None:
            kept = accounts.credential_file(sources.credentials, account)
            if kept.is_file():
                spec = spec.model_copy(update={"account_login": str(kept)})
        return spec
    if provider is None:
        raise ValueError("name an account or a provider")
    found = providers.get(sources.providers, provider)
    if found.provider is None:
        raise ValueError(f"provider '{provider}': {found.error}")
    spec = found.provider
    if spec.endpoint_for(descriptor.provider_protocols) is None:
        accepted = ", ".join(descriptor.provider_protocols) or "none: it runs on an account"
        raise ValueError(
            f"provider '{provider}' speaks {', '.join(spec.endpoints)}, harness "
            f'"{harness}" accepts: {accepted}'
        )
    if model is not None and spec.model_named(model) is None:
        served = ", ".join(m.id for m in spec.models)
        raise ValueError(f"provider '{provider}' has no model '{model}' (it serves: {served})")
    return AgentSpec.resolve(harness, model, provider=(provider, spec))
