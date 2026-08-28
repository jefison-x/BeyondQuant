from app.credentials import MODEL_CATALOG, MODEL_PROVIDERS


def test_opencode_catalog_routes_are_fixed_and_cover_supported_protocols() -> None:
    providers = {item["provider"] for item in MODEL_PROVIDERS}
    assert providers == {"deepseek", "opencode-go", "opencode-zen"}

    runtime_routes = {
        item["runtime_provider"]
        for item in MODEL_CATALOG
        if str(item["provider"]).startswith("opencode-")
    }
    assert runtime_routes == {
        "opencode-go-responses",
        "opencode-go-chat",
        "opencode-go-messages",
        "opencode-zen-responses",
        "opencode-zen-chat",
        "opencode-zen-messages",
    }
    assert all("base_url" not in item for item in MODEL_CATALOG)


def test_model_identity_is_unique_within_each_credential_provider() -> None:
    identities = [(item["provider"], item["model"]) for item in MODEL_CATALOG]
    assert len(identities) == len(set(identities))
