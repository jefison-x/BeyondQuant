"""Trusted runtime resolution for the system Tushare provider."""

from __future__ import annotations

import os
from dataclasses import replace

from .credentials import CredentialStore, CredentialUnavailable
from .data_provider import ProviderCredentialsMissing, TushareConfig, TushareProvider


def resolved_tushare_provider(
    credential_store: CredentialStore,
) -> tuple[TushareProvider, dict[str, object]]:
    try:
        resolved = credential_store.resolve_tushare()
    except CredentialUnavailable as error:
        raise ProviderCredentialsMissing("Tushare credential resolution is unavailable") from error
    if resolved is not None:
        token = str(resolved["token"])
        metadata: dict[str, object] = {
            "source": "credential_store",
            "credential_id": resolved["credential_id"],
            "version": resolved["version"],
        }
    else:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise ProviderCredentialsMissing("Tushare credentials are not configured")
        metadata = {"source": "environment", "credential_id": None, "version": None}
    return TushareProvider(replace(TushareConfig.from_env(), token=token)), metadata
