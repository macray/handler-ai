"""Contract E — what an agent runs as: a harness, the account (`handler.account/v1`, account.py) or
the provider (`handler.provider/v1`, provider.py) its model calls use, and a model. An agent (D.8)
names them; `AgentSpec` is them resolved (the account's login and plan, the provider and its files
for this harness): what `render` takes (B.3)."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .account import Account
from .common import FileSource, HostPath, ResourceName, StrictDocument
from .provider import Provider

HarnessName = Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")]


class NeutralConfig(StrictDocument):
    """Harness-neutral agent configuration (B.2)."""

    model: Annotated[str, Field(min_length=1)] | None = None
    account_connectors: bool = False  # decision 1: off by default (the account's `connectors`)


class AgentSpec(StrictDocument):
    """An agent's harness with its account or its provider (exactly one), resolved."""

    harness: HarnessName
    account: ResourceName | None = None  # its name (accounts/<name>.toml)...
    provider: ResourceName | None = None  # ...or this one's (providers/<name>.toml)
    # the account's credential file, when its harness's login leaves one and it exists (set by
    # the control plane, which keeps it); a token login is resolved at launch
    account_login: HostPath | None = None
    account_plan: str | None = None  # the account's plan (told to the harness, B.3)
    provider_spec: Provider | None = None
    files: dict[str, FileSource] | None = None  # the provider's for this harness (config slots)
    config: NeutralConfig = NeutralConfig()

    @model_validator(mode="after")
    def _account_or_provider(self) -> Self:
        if (self.account is None) == (self.provider is None):
            raise ValueError("name exactly one of 'account' (its login) and 'provider' (its model)")
        return self

    @classmethod
    def resolve(
        cls,
        harness: str,
        model: str | None = None,
        *,
        account: tuple[str, Account] | None = None,
        provider: tuple[str, Provider] | None = None,
    ) -> "AgentSpec":
        """`account` / `provider`: (name, document). ValueError when the account is another
        harness's."""
        if account is not None:
            name, found = account
            if found.harness != harness:
                other = found.harness
                raise ValueError(f"account '{name}' is for harness '{other}', not '{harness}'")
            return cls(
                harness=harness,
                account=name,
                account_plan=found.plan,
                config=NeutralConfig(model=model, account_connectors=found.connectors),
            )
        if provider is None:
            raise ValueError("name exactly one of 'account' (its login) and 'provider' (its model)")
        name, spec = provider
        return cls(
            harness=harness,
            provider=name,
            provider_spec=spec,
            files=(spec.files or {}).get(harness),
            config=NeutralConfig(model=model),
        )
