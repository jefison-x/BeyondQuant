from __future__ import annotations

from app.product_api import _decorate_plugin_center


def test_plugin_projection_only_marks_runtime_reported_identity_active() -> None:
    backend = {
        "policy": {"enabled_plugin_ids": ["guard", "web-search"]},
        "plugins": [
            {"id": "guard", "credential_required": False, "credential_configured": False},
            {"id": "web-search", "credential_required": True, "credential_configured": False},
        ],
    }
    runtime = {"runtime": {"status": "ready", "plugin_profile": "research",
        "composition_hash": "sha256:" + "a" * 64, "enabled_plugin_ids": ["guard"],
        "model_credentials": "resolver", "sdk": "deepseek-harness-sdk==0.1.1rc1",
        "runtime_bin": "deepseek-harness-runtime-bin==0.1.1rc1"}}
    result = _decorate_plugin_center(backend, runtime)
    assert result["plugins"][0]["active"] is True
    assert result["plugins"][1]["active"] is False
    # A resolver is only a credential delivery mechanism. It must not be
    # projected as configured unless readiness reports a real configured key.
    assert result["plugins"][1]["credential_configured"] is False
    assert result["runtime"]["desired_matches_active_plugins"] is False


def test_unavailable_runtime_never_fabricates_active_state() -> None:
    result = _decorate_plugin_center({"policy": {"enabled_plugin_ids": []}, "plugins": [{"id": "guard"}]},
                                     {"runtime": {"status": "unavailable"}})
    assert result["plugins"][0]["active"] is False
    assert result["projection_status"] == "partial"
