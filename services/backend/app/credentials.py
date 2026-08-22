"""Encrypted credentials, model profiles and Agent bindings (ADR-0019)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


ENVELOPE_VERSION = "credential-envelope.v1"
MODEL_CATALOG: tuple[dict[str, object], ...] = (
    {
        "provider": "deepseek",
        "runtime_provider": "deepseek-official",
        "model": "deepseek-v4-flash",
        "display_name": "DeepSeek V4 Flash",
        "reasoning_supported": False,
    },
    {
        "provider": "deepseek",
        "runtime_provider": "deepseek-official",
        "model": "deepseek-chat",
        "display_name": "DeepSeek Chat",
        "reasoning_supported": False,
    },
    {
        "provider": "deepseek",
        "runtime_provider": "deepseek-official",
        "model": "deepseek-reasoner",
        "display_name": "DeepSeek Reasoner",
        "reasoning_supported": True,
    },
)
_CATALOG = {(str(item["provider"]), str(item["model"])): item for item in MODEL_CATALOG}
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_ID = re.compile(r"^(?:cred|profile)_[0-9a-f]{32}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_AGENT_IDS = {"byq-product"}
_PURPOSES = {"model_api_key", "tushare_token"}
_SCOPES = {"user", "system"}
_STATUSES = {"active", "disabled", "revoked"}


class CredentialError(RuntimeError):
    pass


class CredentialNotFound(CredentialError):
    pass


class CredentialConflict(CredentialError):
    pass


class CredentialForbidden(CredentialError):
    pass


class CredentialUnavailable(CredentialError):
    pass


class CredentialPersistenceError(CredentialError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _text(value: object, *, field: str, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ValueError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _principal(value: object, *, field: str = "owner_principal") -> str:
    normalized = _text(value, field=field, maximum=128)
    if _PRINCIPAL.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ principal")
    return normalized


def _identifier(value: object, *, field: str, prefix: str) -> str:
    normalized = _text(value, field=field, maximum=64)
    if not normalized.startswith(f"{prefix}_") or _ID.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not valid")
    return normalized


def _optional_bool(value: object, *, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _expected_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected_version must be a positive integer")
    return value


def _request_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _mask(secret: str) -> str:
    if len(secret) < 8:
        return "configured"
    prefix = "sk-" if secret.startswith("sk-") else ""
    return f"{prefix}…{secret[-4:]}"


def _aad(
    credential_id: str,
    purpose: str,
    provider: str,
    scope: str,
    owner_principal: str | None,
) -> bytes:
    return "\n".join(
        (ENVELOPE_VERSION, credential_id, purpose, provider, scope, owner_principal or "system")
    ).encode()


def _decode_key(value: object, *, key_id: str) -> bytes:
    if not isinstance(value, str):
        raise CredentialUnavailable(f"credential key {key_id!r} is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialUnavailable(f"credential key {key_id!r} is invalid") from exc
    if len(decoded) != 32:
        raise CredentialUnavailable(f"credential key {key_id!r} must contain 32 bytes")
    return decoded


class CredentialCipher:
    def __init__(self, keyring: dict[str, bytes] | None, active_key_id: str | None) -> None:
        self._keyring = dict(keyring or {})
        self.active_key_id = active_key_id
        if active_key_id is not None:
            if _KEY_ID.fullmatch(active_key_id) is None or active_key_id not in self._keyring:
                raise CredentialUnavailable("active credential key is not present in the key ring")
        for key_id, key in self._keyring.items():
            if _KEY_ID.fullmatch(key_id) is None or len(key) != 32:
                raise CredentialUnavailable("credential key ring is invalid")

    @classmethod
    def from_env(cls) -> "CredentialCipher":
        raw = os.environ.get("BYQ_CREDENTIAL_KEYRING", "").strip()
        active = os.environ.get("BYQ_CREDENTIAL_ACTIVE_KEY_ID", "").strip() or None
        if not raw:
            return cls(None, None)
        try:
            pairs = json.loads(raw, object_pairs_hook=lambda values: values)
        except json.JSONDecodeError as exc:
            raise CredentialUnavailable("credential key ring is invalid") from exc
        if not isinstance(pairs, list):
            raise CredentialUnavailable("credential key ring must be a JSON object")
        keyring: dict[str, bytes] = {}
        for item in pairs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise CredentialUnavailable("credential key ring is invalid")
            key_id, encoded = item
            if not isinstance(key_id, str) or key_id in keyring or _KEY_ID.fullmatch(key_id) is None:
                raise CredentialUnavailable("credential key ring contains an invalid or duplicate id")
            keyring[key_id] = _decode_key(encoded, key_id=key_id)
        return cls(keyring, active)

    @classmethod
    def for_test(cls, keyring: dict[str, bytes], active_key_id: str) -> "CredentialCipher":
        return cls(keyring, active_key_id)

    @property
    def configured(self) -> bool:
        return self.active_key_id is not None

    def encrypt(self, secret: str, *, aad: bytes) -> dict[str, object]:
        if self.active_key_id is None:
            raise CredentialUnavailable("credential encryption is not configured")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._keyring[self.active_key_id]).encrypt(nonce, secret.encode(), aad)
        return {
            "envelope_version": ENVELOPE_VERSION,
            "key_id": self.active_key_id,
            "nonce": nonce,
            "ciphertext": ciphertext,
        }

    def decrypt(self, envelope: dict[str, object], *, aad: bytes) -> str:
        if envelope.get("envelope_version") != ENVELOPE_VERSION:
            raise CredentialUnavailable("credential envelope version is unavailable")
        key_id = envelope.get("key_id")
        nonce = envelope.get("nonce")
        ciphertext = envelope.get("ciphertext")
        if not isinstance(key_id, str) or key_id not in self._keyring:
            raise CredentialUnavailable("credential key is unavailable")
        if not isinstance(nonce, bytes) or len(nonce) != 12 or not isinstance(ciphertext, bytes):
            raise CredentialUnavailable("credential envelope is invalid")
        try:
            plaintext = AESGCM(self._keyring[key_id]).decrypt(nonce, ciphertext, aad)
            return plaintext.decode()
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise CredentialUnavailable("credential envelope authentication failed") from exc


class CredentialStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS credentials (
            credential_id TEXT PRIMARY KEY,
            purpose TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope TEXT NOT NULL,
            owner_principal TEXT,
            label TEXT NOT NULL,
            status TEXT NOT NULL,
            masked_descriptor TEXT NOT NULL,
            envelope_version TEXT,
            envelope_key_id TEXT,
            envelope_nonce BYTEA,
            envelope_ciphertext BYTEA,
            version INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            UNIQUE(scope, owner_principal, idempotency_key)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS credentials_owner
            ON credentials(scope, owner_principal, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS credential_audit (
            audit_id TEXT PRIMARY KEY,
            credential_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            owner_principal TEXT,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            request_id TEXT NOT NULL,
            prior_version INTEGER,
            new_version INTEGER,
            outcome TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS model_profiles (
            profile_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            credential_id TEXT NOT NULL REFERENCES credentials(credential_id),
            key_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            temperature DOUBLE PRECISION NOT NULL,
            reasoning_enabled BOOLEAN NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(owner_principal, key_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_model_bindings (
            owner_principal TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            profile_id TEXT REFERENCES model_profiles(profile_id),
            version INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(owner_principal, agent_id)
        )
        """,
    ]

    def __init__(
        self,
        database_url: str | None = None,
        *,
        cipher: CredentialCipher | None = None,
        cipher_error: str | None = None,
    ) -> None:
        self.cipher = cipher or CredentialCipher.from_env()
        self.cipher_error = cipher_error
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise CredentialPersistenceError("credential storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "CredentialStore":
        try:
            cipher = CredentialCipher.from_env()
            return cls(cipher=cipher)
        except CredentialUnavailable as exc:
            # Invalid key configuration disables only credential-backed
            # operations; unrelated Product reads remain available.
            return cls(cipher=CredentialCipher(None, None), cipher_error=str(exc))

    def encryption_status(self) -> dict[str, object]:
        return {
            "configured": self.cipher.configured,
            "envelope_version": ENVELOPE_VERSION,
            "status": "ready" if self.cipher.configured else "unavailable",
        }

    def create_credential(
        self,
        owner: object,
        payload: object,
        *,
        actor: object,
        actor_role: str = "user",
    ) -> dict[str, object]:
        owner_principal = _principal(owner)
        actor_principal = _principal(actor, field="actor_principal")
        if not isinstance(payload, dict):
            raise ValueError("credential request must be an object")
        allowed = {"purpose", "provider", "scope", "label", "secret", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"credential request has unknown fields: {', '.join(unknown)}")
        purpose = _text(payload.get("purpose", "model_api_key"), field="purpose", maximum=32)
        provider = _text(payload.get("provider", "deepseek"), field="provider", maximum=32)
        scope = _text(payload.get("scope", "user"), field="scope", maximum=16)
        label = _text(payload.get("label"), field="label", maximum=120)
        secret = _text(payload.get("secret"), field="secret", maximum=16384)
        idempotency_key = _text(payload.get("idempotency_key"), field="idempotency_key", maximum=128)
        if purpose not in _PURPOSES or scope not in _SCOPES:
            raise ValueError("credential purpose or scope is not supported")
        if purpose == "tushare_token" and (provider != "tushare" or scope != "system"):
            raise ValueError("Tushare credentials must use the system scope and tushare provider")
        if purpose == "model_api_key" and provider != "deepseek":
            raise ValueError("model credential provider is not in the BYQ catalogue")
        if scope == "system" and actor_role != "admin":
            raise CredentialForbidden("system credentials require admin role")
        record_owner = owner_principal if scope == "user" else None
        request_hash = _request_hash(
            {
                "purpose": purpose,
                "provider": provider,
                "scope": scope,
                "owner": record_owner,
                "label": label,
                "secret_sha256": _secret_digest(secret),
            }
        )
        credential_id = _new_id("cred")
        envelope = self.cipher.encrypt(
            secret,
            aad=_aad(credential_id, purpose, provider, scope, record_owner),
        )
        now = _now()
        try:
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    """SELECT * FROM credentials
                    WHERE scope = :scope
                      AND owner_principal IS NOT DISTINCT FROM :owner_principal
                      AND idempotency_key = :idempotency_key""",
                    {
                        "scope": scope,
                        "owner_principal": record_owner,
                        "idempotency_key": idempotency_key,
                    },
                )
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        raise CredentialConflict("credential idempotency key was reused")
                    return self._public_credential(existing)
                execute(
                    connection,
                    """INSERT INTO credentials
                    (credential_id, purpose, provider, scope, owner_principal, label,
                     status, masked_descriptor, envelope_version, envelope_key_id,
                     envelope_nonce, envelope_ciphertext, version, idempotency_key,
                     request_hash, created_by, updated_by, created_at, updated_at, revoked_at)
                    VALUES (:credential_id, :purpose, :provider, :scope, :owner_principal,
                            :label, 'active', :masked, :envelope_version, :key_id,
                            :nonce, :ciphertext, 1, :idempotency_key, :request_hash,
                            :actor, :actor, :created_at, :updated_at, NULL)""",
                    {
                        "credential_id": credential_id,
                        "purpose": purpose,
                        "provider": provider,
                        "scope": scope,
                        "owner_principal": record_owner,
                        "label": label,
                        "masked": _mask(secret),
                        **envelope,
                        "idempotency_key": idempotency_key,
                        "request_hash": request_hash,
                        "actor": actor_principal,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                self._audit(
                    connection,
                    credential_id=credential_id,
                    scope=scope,
                    owner=record_owner,
                    actor=actor_principal,
                    action="created",
                    request_id=idempotency_key,
                    prior_version=None,
                    new_version=1,
                )
        except IntegrityError as exc:
            raise CredentialConflict("credential request conflicts with existing state") from exc
        return self.get_credential(credential_id, owner=owner_principal, actor_role=actor_role)

    def list_credentials(self, owner: object, *, actor_role: str = "user") -> list[dict[str, object]]:
        owner_principal = _principal(owner)
        if actor_role == "admin":
            rows = self._execute(
                """SELECT * FROM credentials
                WHERE (scope = 'user' AND owner_principal = :owner)
                   OR scope = 'system'
                ORDER BY created_at DESC, credential_id DESC""",
                {"owner": owner_principal},
            )
        else:
            rows = self._execute(
                """SELECT * FROM credentials
                WHERE scope = 'user' AND owner_principal = :owner
                ORDER BY created_at DESC, credential_id DESC""",
                {"owner": owner_principal},
            )
        return [self._public_credential(row) for row in rows]

    def get_credential(
        self,
        credential_id: object,
        *,
        owner: object,
        actor_role: str = "user",
    ) -> dict[str, object]:
        credential_id = _identifier(credential_id, field="credential_id", prefix="cred")
        owner_principal = _principal(owner)
        row = self._fetch_one(
            "SELECT * FROM credentials WHERE credential_id = :credential_id",
            {"credential_id": credential_id},
        )
        if row is None or not self._can_access(row, owner_principal, actor_role):
            raise CredentialNotFound("credential not found")
        return self._public_credential(row)

    def update_credential(
        self,
        credential_id: object,
        owner: object,
        payload: object,
        *,
        actor: object,
        actor_role: str = "user",
    ) -> dict[str, object]:
        credential_id = _identifier(credential_id, field="credential_id", prefix="cred")
        owner_principal = _principal(owner)
        actor_principal = _principal(actor, field="actor_principal")
        if not isinstance(payload, dict):
            raise ValueError("credential update must be an object")
        allowed = {"label", "secret", "status", "expected_version", "request_id"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"credential update has unknown fields: {', '.join(unknown)}")
        expected = _expected_version(payload.get("expected_version"))
        request_id = _text(payload.get("request_id"), field="request_id", maximum=128)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM credentials WHERE credential_id = :credential_id FOR UPDATE",
                {"credential_id": credential_id},
            )
            if row is None or not self._can_access(row, owner_principal, actor_role):
                raise CredentialNotFound("credential not found")
            if row["status"] == "revoked":
                raise CredentialConflict("revoked credential cannot be updated")
            if row["version"] != expected:
                raise CredentialConflict("credential version conflict")
            label = _text(payload.get("label", row["label"]), field="label", maximum=120)
            status = payload.get("status", row["status"])
            if status not in {"active", "disabled"}:
                raise ValueError("credential status must be active or disabled")
            envelope_version = row["envelope_version"]
            key_id = row["envelope_key_id"]
            nonce = row["envelope_nonce"]
            ciphertext = row["envelope_ciphertext"]
            masked = row["masked_descriptor"]
            action = "updated"
            if "secret" in payload:
                secret = _text(payload.get("secret"), field="secret", maximum=16384)
                envelope = self.cipher.encrypt(
                    secret,
                    aad=_aad(
                        credential_id,
                        str(row["purpose"]),
                        str(row["provider"]),
                        str(row["scope"]),
                        row["owner_principal"],
                    ),
                )
                envelope_version = envelope["envelope_version"]
                key_id = envelope["key_id"]
                nonce = envelope["nonce"]
                ciphertext = envelope["ciphertext"]
                masked = _mask(secret)
                action = "secret_replaced"
            elif status != row["status"]:
                action = "enabled" if status == "active" else "disabled"
            new_version = expected + 1
            execute(
                connection,
                """UPDATE credentials SET label = :label, status = :status,
                   masked_descriptor = :masked, envelope_version = :envelope_version,
                   envelope_key_id = :key_id, envelope_nonce = :nonce,
                   envelope_ciphertext = :ciphertext, version = :version,
                   updated_by = :actor, updated_at = :updated_at
                   WHERE credential_id = :credential_id""",
                {
                    "credential_id": credential_id,
                    "label": label,
                    "status": status,
                    "masked": masked,
                    "envelope_version": envelope_version,
                    "key_id": key_id,
                    "nonce": nonce,
                    "ciphertext": ciphertext,
                    "version": new_version,
                    "actor": actor_principal,
                    "updated_at": _now(),
                },
            )
            self._audit(
                connection,
                credential_id=credential_id,
                scope=str(row["scope"]),
                owner=row["owner_principal"],
                actor=actor_principal,
                action=action,
                request_id=request_id,
                prior_version=expected,
                new_version=new_version,
            )
        return self.get_credential(credential_id, owner=owner_principal, actor_role=actor_role)

    def revoke_credential(
        self,
        credential_id: object,
        owner: object,
        *,
        actor: object,
        expected_version: object,
        request_id: object,
        actor_role: str = "user",
    ) -> dict[str, object]:
        credential_id = _identifier(credential_id, field="credential_id", prefix="cred")
        owner_principal = _principal(owner)
        actor_principal = _principal(actor, field="actor_principal")
        expected = _expected_version(expected_version)
        request_id = _text(request_id, field="request_id", maximum=128)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM credentials WHERE credential_id = :credential_id FOR UPDATE",
                {"credential_id": credential_id},
            )
            if row is None or not self._can_access(row, owner_principal, actor_role):
                raise CredentialNotFound("credential not found")
            if row["status"] == "revoked":
                return self._public_credential(row)
            if row["version"] != expected:
                raise CredentialConflict("credential version conflict")
            new_version = expected + 1
            now = _now()
            execute(
                connection,
                """UPDATE credentials SET status = 'revoked',
                   envelope_version = NULL, envelope_key_id = NULL,
                   envelope_nonce = NULL, envelope_ciphertext = NULL,
                   version = :version, updated_by = :actor,
                   updated_at = :updated_at, revoked_at = :updated_at
                   WHERE credential_id = :credential_id""",
                {
                    "credential_id": credential_id,
                    "version": new_version,
                    "actor": actor_principal,
                    "updated_at": now,
                },
            )
            profile_rows = execute(
                connection,
                "SELECT profile_id FROM model_profiles WHERE credential_id = :credential_id",
                {"credential_id": credential_id},
            )
            for profile in profile_rows:
                execute(
                    connection,
                    """UPDATE agent_model_bindings SET
                       version = version + 1, updated_at = :updated_at
                       WHERE profile_id = :profile_id""",
                    {"profile_id": profile["profile_id"], "updated_at": now},
                )
            execute(
                connection,
                """UPDATE model_profiles SET status = 'disabled',
                   version = version + 1, updated_at = :updated_at
                   WHERE credential_id = :credential_id""",
                {"credential_id": credential_id, "updated_at": now},
            )
            self._audit(
                connection,
                credential_id=credential_id,
                scope=str(row["scope"]),
                owner=row["owner_principal"],
                actor=actor_principal,
                action="revoked",
                request_id=request_id,
                prior_version=expected,
                new_version=new_version,
            )
        return self.get_credential(credential_id, owner=owner_principal, actor_role=actor_role)

    def list_audit(self, owner: object, *, limit: int = 100) -> list[dict[str, object]]:
        owner_principal = _principal(owner)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("audit limit must be between 1 and 200")
        return self._execute(
            """SELECT audit_id, credential_id, scope, owner_principal,
                      actor_principal, action, request_id, prior_version,
                      new_version, outcome, created_at
               FROM credential_audit
               WHERE owner_principal = :owner
               ORDER BY created_at DESC, audit_id DESC LIMIT :limit""",
            {"owner": owner_principal, "limit": limit},
        )

    def create_profile(self, owner: object, payload: object) -> dict[str, object]:
        owner_principal = _principal(owner)
        if not isinstance(payload, dict):
            raise ValueError("model profile request must be an object")
        allowed = {
            "credential_id", "key_name", "display_name", "provider", "model",
            "temperature", "reasoning_enabled",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"model profile request has unknown fields: {', '.join(unknown)}")
        credential_id = _identifier(payload.get("credential_id"), field="credential_id", prefix="cred")
        key_name = _text(payload.get("key_name"), field="key_name", maximum=64)
        display_name = _text(payload.get("display_name"), field="display_name", maximum=120)
        provider = _text(payload.get("provider"), field="provider", maximum=32)
        model = _text(payload.get("model"), field="model", maximum=96)
        catalog = _CATALOG.get((provider, model))
        if catalog is None:
            raise ValueError("model profile is not in the BYQ catalogue")
        temperature = payload.get("temperature", 0.2)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ValueError("temperature must be numeric")
        temperature = float(temperature)
        if temperature < 0 or temperature > 2:
            raise ValueError("temperature must be between 0 and 2")
        reasoning_enabled = _optional_bool(
            payload.get("reasoning_enabled"),
            field="reasoning_enabled",
            default=False,
        )
        if reasoning_enabled and not catalog["reasoning_supported"]:
            raise ValueError("selected model does not support reasoning mode")
        credential = self._fetch_one(
            "SELECT * FROM credentials WHERE credential_id = :credential_id",
            {"credential_id": credential_id},
        )
        if (
            credential is None
            or credential["scope"] != "user"
            or credential["owner_principal"] != owner_principal
            or credential["purpose"] != "model_api_key"
            or credential["provider"] != provider
            or credential["status"] != "active"
        ):
            raise CredentialNotFound("active model credential not found")
        profile_id = _new_id("profile")
        now = _now()
        try:
            self._execute(
                """INSERT INTO model_profiles
                (profile_id, owner_principal, credential_id, key_name,
                 display_name, provider, model, temperature, reasoning_enabled,
                 status, version, created_at, updated_at)
                VALUES (:profile_id, :owner, :credential_id, :key_name,
                        :display_name, :provider, :model, :temperature,
                        :reasoning_enabled, 'active', 1, :created_at, :updated_at)""",
                {
                    "profile_id": profile_id,
                    "owner": owner_principal,
                    "credential_id": credential_id,
                    "key_name": key_name,
                    "display_name": display_name,
                    "provider": provider,
                    "model": model,
                    "temperature": temperature,
                    "reasoning_enabled": reasoning_enabled,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            raise CredentialConflict("model profile key already exists") from exc
        return self.get_profile(profile_id, owner=owner_principal)

    def list_profiles(self, owner: object) -> list[dict[str, object]]:
        owner_principal = _principal(owner)
        rows = self._execute(
            """SELECT p.*, c.status AS credential_status
               FROM model_profiles p JOIN credentials c USING(credential_id)
               WHERE p.owner_principal = :owner
               ORDER BY p.created_at DESC, p.profile_id DESC""",
            {"owner": owner_principal},
        )
        return [self._public_profile(row) for row in rows]

    def get_profile(self, profile_id: object, *, owner: object) -> dict[str, object]:
        profile_id = _identifier(profile_id, field="profile_id", prefix="profile")
        owner_principal = _principal(owner)
        row = self._fetch_one(
            """SELECT p.*, c.status AS credential_status
               FROM model_profiles p JOIN credentials c USING(credential_id)
               WHERE p.profile_id = :profile_id AND p.owner_principal = :owner""",
            {"profile_id": profile_id, "owner": owner_principal},
        )
        if row is None:
            raise CredentialNotFound("model profile not found")
        return self._public_profile(row)

    def delete_profile(
        self,
        profile_id: object,
        owner: object,
        *,
        expected_version: object,
    ) -> dict[str, object]:
        profile_id = _identifier(profile_id, field="profile_id", prefix="profile")
        owner_principal = _principal(owner)
        expected = _expected_version(expected_version)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """SELECT * FROM model_profiles
                   WHERE profile_id = :profile_id AND owner_principal = :owner
                   FOR UPDATE""",
                {"profile_id": profile_id, "owner": owner_principal},
            )
            if row is None:
                raise CredentialNotFound("model profile not found")
            if row["version"] != expected:
                raise CredentialConflict("model profile version conflict")
            now = _now()
            execute(
                connection,
                """UPDATE agent_model_bindings SET profile_id = NULL,
                   version = version + 1, updated_at = :updated_at
                   WHERE owner_principal = :owner AND profile_id = :profile_id""",
                {"owner": owner_principal, "profile_id": profile_id, "updated_at": now},
            )
            execute(
                connection,
                """UPDATE model_profiles SET status = 'deleted', version = version + 1,
                   updated_at = :updated_at WHERE profile_id = :profile_id""",
                {"profile_id": profile_id, "updated_at": now},
            )
        return self.get_profile(profile_id, owner=owner_principal)

    def list_bindings(self, owner: object) -> list[dict[str, object]]:
        owner_principal = _principal(owner)
        rows = self._execute(
            """SELECT b.owner_principal, b.agent_id, b.profile_id, b.version,
                      b.updated_at, p.display_name, p.model, p.status AS profile_status
               FROM agent_model_bindings b
               LEFT JOIN model_profiles p ON p.profile_id = b.profile_id
               WHERE b.owner_principal = :owner ORDER BY b.agent_id""",
            {"owner": owner_principal},
        )
        by_agent = {str(row["agent_id"]): row for row in rows}
        return [self._public_binding(by_agent.get(agent_id), owner_principal, agent_id) for agent_id in sorted(_AGENT_IDS)]

    def bind(
        self,
        owner: object,
        agent_id: object,
        profile_id: object | None,
        *,
        expected_version: object | None = None,
    ) -> dict[str, object]:
        owner_principal = _principal(owner)
        agent = _text(agent_id, field="agent_id", maximum=64)
        if agent not in _AGENT_IDS:
            raise ValueError("agent_id is not bindable")
        profile: dict[str, object] | None = None
        if profile_id is not None:
            parsed_profile_id = _identifier(profile_id, field="profile_id", prefix="profile")
            profile = self._fetch_one(
                """SELECT p.*, c.status AS credential_status
                   FROM model_profiles p JOIN credentials c USING(credential_id)
                   WHERE p.profile_id = :profile_id AND p.owner_principal = :owner""",
                {"profile_id": parsed_profile_id, "owner": owner_principal},
            )
            if (
                profile is None
                or profile["status"] != "active"
                or profile["credential_status"] != "active"
            ):
                raise CredentialNotFound("active model profile not found")
        current = self._fetch_one(
            """SELECT * FROM agent_model_bindings
               WHERE owner_principal = :owner AND agent_id = :agent_id""",
            {"owner": owner_principal, "agent_id": agent},
        )
        if current is not None:
            expected = _expected_version(expected_version)
            if current["version"] != expected:
                raise CredentialConflict("Agent binding version conflict")
            version = expected + 1
        else:
            if expected_version not in {None, 0}:
                raise CredentialConflict("Agent binding version conflict")
            version = 1
        now = _now()
        self._execute(
            """INSERT INTO agent_model_bindings
            (owner_principal, agent_id, profile_id, version, updated_at)
            VALUES (:owner, :agent_id, :profile_id, :version, :updated_at)
            ON CONFLICT(owner_principal, agent_id) DO UPDATE SET
                profile_id = excluded.profile_id,
                version = excluded.version,
                updated_at = excluded.updated_at""",
            {
                "owner": owner_principal,
                "agent_id": agent,
                "profile_id": None if profile is None else profile["profile_id"],
                "version": version,
                "updated_at": now,
            },
        )
        return next(item for item in self.list_bindings(owner_principal) if item["agent_id"] == agent)

    def resolve_model(self, owner: object, agent_id: object) -> dict[str, object] | None:
        owner_principal = _principal(owner)
        agent = _text(agent_id, field="agent_id", maximum=64)
        if agent not in _AGENT_IDS:
            raise CredentialNotFound("Agent binding not found")
        row = self._fetch_one(
            """SELECT b.profile_id, p.provider, p.model, p.temperature,
                      p.reasoning_enabled, p.status AS profile_status,
                      c.credential_id, c.purpose, c.scope, c.owner_principal,
                      c.status AS credential_status, c.envelope_version,
                      c.envelope_key_id, c.envelope_nonce, c.envelope_ciphertext
               FROM agent_model_bindings b
               LEFT JOIN model_profiles p ON p.profile_id = b.profile_id
               LEFT JOIN credentials c ON c.credential_id = p.credential_id
               WHERE b.owner_principal = :owner AND b.agent_id = :agent_id""",
            {"owner": owner_principal, "agent_id": agent},
        )
        if row is None or row["profile_id"] is None:
            return None
        if (
            row["profile_status"] != "active"
            or row["credential_status"] != "active"
            or row["scope"] != "user"
            or row["owner_principal"] != owner_principal
            or row["purpose"] != "model_api_key"
        ):
            raise CredentialUnavailable("selected model binding is unavailable")
        catalog = _CATALOG.get((str(row["provider"]), str(row["model"])))
        if catalog is None:
            raise CredentialUnavailable("selected model is unavailable")
        secret = self.cipher.decrypt(
            {
                "envelope_version": row["envelope_version"],
                "key_id": row["envelope_key_id"],
                "nonce": row["envelope_nonce"],
                "ciphertext": row["envelope_ciphertext"],
            },
            aad=_aad(
                str(row["credential_id"]),
                str(row["purpose"]),
                str(row["provider"]),
                str(row["scope"]),
                owner_principal,
            ),
        )
        return {
            "source": "user_binding",
            "provider": catalog["runtime_provider"],
            "model": row["model"],
            "temperature": row["temperature"],
            "reasoning_enabled": bool(row["reasoning_enabled"]),
            "api_key": secret,
        }

    def resolve_tushare(self) -> dict[str, object] | None:
        """Resolve the one active system Tushare credential inside Backend.

        This method is deliberately not exposed through an HTTP resolver.  It
        is consumed only by the Backend-owned provider adapter (ADR-0019).
        Multiple active credentials fail closed instead of selecting one by
        recency and silently charging an unexpected Tushare account.
        """
        rows = self._execute(
            """SELECT * FROM credentials
               WHERE purpose = 'tushare_token' AND provider = 'tushare'
                 AND scope = 'system' AND status = 'active'
               ORDER BY updated_at DESC, credential_id DESC LIMIT 2"""
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise CredentialUnavailable("multiple active Tushare credentials are configured")
        row = rows[0]
        secret = self.cipher.decrypt(
            {
                "envelope_version": row["envelope_version"],
                "key_id": row["envelope_key_id"],
                "nonce": row["envelope_nonce"],
                "ciphertext": row["envelope_ciphertext"],
            },
            aad=_aad(
                str(row["credential_id"]),
                "tushare_token",
                "tushare",
                "system",
                None,
            ),
        )
        return {
            "source": "credential_store",
            "credential_id": row["credential_id"],
            "version": row["version"],
            "token": secret,
        }

    def assert_tushare_create_allowed(self, idempotency_key: object) -> None:
        """Allow a create replay, but reject a second live system token."""
        key = _text(idempotency_key, field="idempotency_key", maximum=128)
        rows = self._execute(
            """SELECT idempotency_key FROM credentials
               WHERE purpose = 'tushare_token' AND provider = 'tushare'
                 AND scope = 'system' AND status <> 'revoked' LIMIT 2"""
        )
        if any(row["idempotency_key"] != key for row in rows):
            raise CredentialConflict("replace or revoke the existing Tushare credential")

    def rewrap_active(self, *, actor: object, request_id: object) -> dict[str, int]:
        actor_principal = _principal(actor, field="actor_principal")
        request_id = _text(request_id, field="request_id", maximum=128)
        if not self.cipher.configured:
            raise CredentialUnavailable("credential encryption is not configured")
        rows = self._execute(
            """SELECT * FROM credentials
               WHERE status IN ('active', 'disabled')
                 AND envelope_ciphertext IS NOT NULL
               ORDER BY credential_id LIMIT 500"""
        )
        rewrapped = 0
        for row in rows:
            if row["envelope_key_id"] == self.cipher.active_key_id:
                continue
            aad = _aad(
                str(row["credential_id"]),
                str(row["purpose"]),
                str(row["provider"]),
                str(row["scope"]),
                row["owner_principal"],
            )
            secret = self.cipher.decrypt(
                {
                    "envelope_version": row["envelope_version"],
                    "key_id": row["envelope_key_id"],
                    "nonce": row["envelope_nonce"],
                    "ciphertext": row["envelope_ciphertext"],
                },
                aad=aad,
            )
            envelope = self.cipher.encrypt(secret, aad=aad)
            with self._transaction() as connection:
                current = fetch_one(
                    connection,
                    "SELECT * FROM credentials WHERE credential_id = :credential_id FOR UPDATE",
                    {"credential_id": row["credential_id"]},
                )
                if current is None or current["version"] != row["version"]:
                    continue
                new_version = int(row["version"]) + 1
                execute(
                    connection,
                    """UPDATE credentials SET envelope_version = :envelope_version,
                       envelope_key_id = :key_id, envelope_nonce = :nonce,
                       envelope_ciphertext = :ciphertext, version = :version,
                       updated_by = :actor, updated_at = :updated_at
                       WHERE credential_id = :credential_id""",
                    {
                        "credential_id": row["credential_id"],
                        **envelope,
                        "version": new_version,
                        "actor": actor_principal,
                        "updated_at": _now(),
                    },
                )
                self._audit(
                    connection,
                    credential_id=str(row["credential_id"]),
                    scope=str(row["scope"]),
                    owner=row["owner_principal"],
                    actor=actor_principal,
                    action="rewrapped",
                    request_id=request_id,
                    prior_version=int(row["version"]),
                    new_version=new_version,
                )
                rewrapped += 1
        return {"rewrapped": rewrapped, "examined": len(rows)}

    @staticmethod
    def _can_access(row: dict[str, object], owner: str, actor_role: str) -> bool:
        return (
            row["scope"] == "user" and row["owner_principal"] == owner
        ) or (
            row["scope"] == "system" and actor_role == "admin"
        )

    @staticmethod
    def _public_credential(row: dict[str, object]) -> dict[str, object]:
        return {
            "credential_id": row["credential_id"],
            "purpose": row["purpose"],
            "provider": row["provider"],
            "scope": row["scope"],
            "label": row["label"],
            "status": row["status"],
            "configured": row["status"] in {"active", "disabled"} and row["envelope_ciphertext"] is not None,
            "masked": row["masked_descriptor"] if row["status"] != "revoked" else "revoked",
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _public_profile(row: dict[str, object]) -> dict[str, object]:
        return {
            "profile_id": row["profile_id"],
            "credential_id": row["credential_id"],
            "key_name": row["key_name"],
            "display_name": row["display_name"],
            "provider": row["provider"],
            "model": row["model"],
            "temperature": row["temperature"],
            "reasoning_enabled": bool(row["reasoning_enabled"]),
            "status": row["status"],
            "available": row["status"] == "active" and row["credential_status"] == "active",
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _public_binding(
        row: dict[str, object] | None,
        owner: str,
        agent_id: str,
    ) -> dict[str, object]:
        if row is None:
            return {
                "owner_principal": owner,
                "agent_id": agent_id,
                "agent_name": "小霸 Product Agent",
                "profile_id": None,
                "effective_source": "system_default",
                "available": True,
                "version": 0,
                "updated_at": None,
            }
        available = row["profile_id"] is None or row["profile_status"] == "active"
        return {
            "owner_principal": owner,
            "agent_id": agent_id,
            "agent_name": "小霸 Product Agent",
            "profile_id": row["profile_id"],
            "profile_name": row["display_name"],
            "model": row["model"],
            "effective_source": "personal" if row["profile_id"] else "system_default",
            "available": available,
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _audit(
        connection,
        *,
        credential_id: str,
        scope: str,
        owner: str | None,
        actor: str,
        action: str,
        request_id: str,
        prior_version: int | None,
        new_version: int,
    ) -> None:
        execute(
            connection,
            """INSERT INTO credential_audit
            (audit_id, credential_id, scope, owner_principal, actor_principal,
             action, request_id, prior_version, new_version, outcome, created_at)
            VALUES (:audit_id, :credential_id, :scope, :owner_principal,
                    :actor_principal, :action, :request_id, :prior_version,
                    :new_version, 'completed', :created_at)""",
            {
                "audit_id": f"audit_{uuid.uuid4().hex}",
                "credential_id": credential_id,
                "scope": scope,
                "owner_principal": owner,
                "actor_principal": actor,
                "action": action,
                "request_id": request_id,
                "prior_version": prior_version,
                "new_version": new_version,
                "created_at": _now(),
            },
        )


def authorize_resolver(presented: str | None, configured: str | None) -> None:
    if not configured or not presented or not hmac.compare_digest(presented, configured):
        raise CredentialForbidden("credential resolver authentication failed")
