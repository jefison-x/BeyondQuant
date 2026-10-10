"""Static contract for the BYQ ACP single-image candidate overlay (evaluation only).

Scope: this file checks ONLY the additive single-image candidate

    services/acp_unified/Dockerfile
    services/acp_unified/entrypoint.sh
    compose.dsh-acp-single-image-candidate.yml

It reads the candidate compose overlay and asserts the static declarations that
overlay makes. It does **not** compare the overlay field-for-field against the
accepted three-image topology (``compose.dsh-acp-rc2-candidate.yml`` /
``compose.yml``) and does not re-assert those accepted contracts, which live in
``tests/architecture/``. It is Docker-free, keyless, and reads no env/secret
file. Run directly::

    python3 services/acp_unified/tests/test_single_image_contract.py
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "compose.dsh-acp-single-image-candidate.yml"
DOCKERFILE = ROOT / "services/acp_unified/Dockerfile"
ENTRYPOINT = ROOT / "services/acp_unified/entrypoint.sh"

ROLES = ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")
ROLE_PARAM = {
    "runtime-adapter": "adapter",
    "acp-product-runner": "product",
    "acp-judgment-runner": "judgment",
}
# Secret env vars that MUST be satisfied/fail-closed by Compose interpolation
# (never baked into the image).
ROLE_SECRET_ENV = {
    "runtime-adapter": (
        "BYQ_RUNTIME_AUTHORITY_TOKEN",
        "BYQ_RUNTIME_JUDGMENT_TOKEN",
        "BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET",
        "BYQ_MCP_ACP_DISCOVERY_TOKEN",
        "BYQ_MCP_ACP_SIGNING_KEY",
        "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY",
        "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET",
    ),
    "acp-product-runner": ("BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET",),
    "acp-judgment-runner": ("BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET",),
}
SECRET_TOKENS = ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY")


class AcpSingleImageCandidateOverlayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.services = cls.compose["services"]
        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        cls.entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    def test_one_image_reference_serves_all_three_roles(self) -> None:
        self.assertEqual(set(self.services), set(ROLES))
        images = {name: self.services[name]["image"] for name in ROLES}
        # Static declaration only: the three services share one image expression
        # and one build definition, so one local build yields one local image ID.
        self.assertEqual(len(set(images.values())), 1, images)
        self.assertEqual(
            images["runtime-adapter"],
            "${BYQ_ACP_UNIFIED_IMAGE:-byq-acp-unified:candidate}",
        )
        builds = [self.services[name].get("build") for name in ROLES]
        self.assertTrue(all(isinstance(build, dict) for build in builds), builds)
        self.assertEqual(len({repr(build) for build in builds}), 1, builds)
        for build in builds:
            self.assertEqual(build["context"], ".")
            self.assertEqual(build["dockerfile"], "services/acp_unified/Dockerfile")
        # The unified image is referenced by exactly the three role services.
        self.assertEqual(
            sum(
                1
                for svc in self.services.values()
                if svc.get("image") == images["runtime-adapter"]
            ),
            3,
        )

    def test_role_boundaries_are_per_service_in_the_candidate_overlay(self) -> None:
        # Asserts the candidate overlay declares per-service boundaries; it does
        # not claim field-for-field equivalence with the accepted topology.
        adapter = self.services["runtime-adapter"]
        product = self.services["acp-product-runner"]
        judgment = self.services["acp-judgment-runner"]

        self.assertEqual(adapter["user"], "10002:10002")
        self.assertEqual(adapter["cap_drop"], ["NET_RAW"])
        self.assertEqual(adapter["group_add"], ["10005", "10006"])
        self.assertEqual(
            set(adapter["networks"]), {"byq_product", "byq_acp_judgment"}
        )

        for runner, network in (
            (product, "byq_product"),
            (judgment, "byq_acp_judgment"),
        ):
            self.assertEqual(runner["user"], "0:0")
            self.assertIs(runner["read_only"], True)
            self.assertEqual(runner["cap_drop"], ["ALL"])
            self.assertEqual(
                runner["cap_add"], ["CHOWN", "SETGID", "SETUID", "KILL"]
            )
            self.assertEqual(runner["security_opt"], ["no-new-privileges:true"])
            self.assertEqual(set(runner["networks"]), {network})

        for name in ROLES:
            self.assertEqual(
                self.services[name]["environment"]["BYQ_ACP_ROLE"], ROLE_PARAM[name]
            )

    def test_judgment_network_is_internal_and_volumes_are_per_role(self) -> None:
        networks = self.compose["networks"]
        self.assertEqual(networks["byq_acp_judgment"]["driver"], "bridge")
        self.assertIs(networks["byq_acp_judgment"]["internal"], True)
        self.assertIs(networks["byq_product"].get("internal"), None)

        product_mounts = _volume_sources(self.services["acp-product-runner"])
        judgment_mounts = _volume_sources(self.services["acp-judgment-runner"])
        # judgment sessions/state/control must not be shared with the product role.
        self.assertIn("byq_acp_judgment_sessions", judgment_mounts)
        self.assertIn("byq_acp_runner_state", judgment_mounts)
        self.assertIn("byq_acp_runner_control", judgment_mounts)
        self.assertNotIn("byq_acp_judgment_sessions", product_mounts)
        self.assertNotIn("byq_acp_runner_state", product_mounts)

    def test_role_secrets_are_compose_only_and_fail_closed(self) -> None:
        for name, secret_envs in ROLE_SECRET_ENV.items():
            environment = self.services[name]["environment"]
            for key in secret_envs:
                self.assertIn(key, environment, f"{name}:{key}")
                self.assertIn(
                    ":?",
                    str(environment[key]),
                    f"{name}:{key} must require an explicit secret",
                )
        # No secret value or secret env name may be baked into the image.
        for line in self.dockerfile.splitlines():
            stripped = line.strip()
            if stripped.startswith("ENV") or stripped.startswith("ARG"):
                upper = stripped.upper()
                self.assertFalse(
                    any(token in upper for token in SECRET_TOKENS),
                    f"secret-looking line baked in Dockerfile: {stripped}",
                )

    def test_dockerfile_verifies_all_three_roles_before_any_clone(self) -> None:
        clone_at = self.dockerfile.index(
            'git clone --depth 1 --branch "$BYQ_DSH_BUILD_RELEASE_ID"'
        )
        for role in ("adapter", "ordinary_runner", "judgment_runner"):
            marker = f"--verify-build-inputs --role {role} --root /opt/byq-authoritative"
            self.assertIn(marker, self.dockerfile, role)
            self.assertLess(self.dockerfile.index(marker), clone_at, role)
        # Build identity is resolver-fed; no literal commit/hash is hard-coded.
        self.assertNotIn("639ed015397290b3745d163aafe02ffee4aa3f84", self.dockerfile)
        self.assertIn('"$BYQ_DSH_BUILD_SOURCE_COMMIT"', self.dockerfile)
        self.assertIn('"$BYQ_DSH_BUILD_PNPM_LOCK_SHA256  pnpm-lock.yaml"', self.dockerfile)

    def test_image_defaults_to_the_unprivileged_byq_identity(self) -> None:
        user_lines = [
            line.strip()
            for line in self.dockerfile.splitlines()
            if line.strip().startswith("USER ")
        ]
        self.assertEqual(user_lines, ["USER byq"], user_lines)

    def _adapter_branch_code(self) -> list[str]:
        lines = self.entrypoint.splitlines()
        start = next(
            i for i, line in enumerate(lines) if line.strip() == "adapter)"
        )
        end = next(
            i for i in range(start + 1, len(lines)) if lines[i].strip() == ";;"
        )
        return [
            line.strip()
            for line in lines[start + 1 : end]
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_entrypoint_is_fail_closed_for_role_and_adapter_identity(self) -> None:
        for role in ("adapter", "product", "judgment"):
            self.assertIn(f"{role})", self.entrypoint, role)
        self.assertIn("BYQ_ACP_ROLE", self.entrypoint)
        self.assertIn("exit 64", self.entrypoint)  # unknown/unset role

        # The adapter branch must contain a real identity guard (not a comment)
        # and it must run before the `exec uvicorn` in that same branch.
        adapter_code = self._adapter_branch_code()
        joined = " ".join(adapter_code)
        self.assertIn("id -u", joined)
        self.assertIn("id -g", joined)
        self.assertIn("10002", joined)
        self.assertIn("exit 77", adapter_code)  # exact command, comments excluded
        guard_at = adapter_code.index("exit 77")
        uvicorn_at = next(
            i
            for i, line in enumerate(adapter_code)
            if "uvicorn app.main:app" in line
        )
        self.assertTrue(adapter_code[uvicorn_at].startswith("exec "))
        self.assertLess(guard_at, uvicorn_at)


def _volume_sources(service: dict) -> set[str]:
    sources: set[str] = set()
    for mount in service.get("volumes", []):
        if isinstance(mount, str):
            sources.add(mount.split(":", 1)[0])
        elif isinstance(mount, dict):
            sources.add(mount["source"])
    return sources


if __name__ == "__main__":
    unittest.main()
