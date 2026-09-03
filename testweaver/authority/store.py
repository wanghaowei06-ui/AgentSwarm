"""Append-only TestWeaver authority records backed by a DB-API connection.

The native AgentTeams control plane remains the owner of execution.  This
module stores only TestWeaver facts and opaque references.  It never starts a
task, sends a message, reads a provider, or stores prompt/secret bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterator

from testweaver.contracts.validator import canonical_hash


class AuthorityError(ValueError):
    """Raised when an authority record is malformed or unsafe."""


class AuthorityConflict(AuthorityError):
    """Raised when an idempotency key is reused for different facts."""


_HASH: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^\S{1,512}$")
_REF: Final[re.Pattern[str]] = re.compile(r"^\S{1,2048}$")
_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "prompt_text",
        "body",
        "content",
        "secret",
        "api_key",
        "apikey",
        "password",
        "authorization",
        "access_token",
        "token",
        "credential",
        "result_text",
        "output",
        "message",
        "text",
        "input",
        "arguments",
        "response",
    }
)
_AUTHORITY_TABLES: Final[frozenset[str]] = frozenset(
    {
        "tw_authority_events",
        "tw_capsules",
        "tw_capsule_hits",
        "tw_hitl_events",
        "tw_oracle_results",
        "tw_side_effect_ledger",
    }
)
_TABLE_REFERENCE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\b", re.IGNORECASE
)
_COLUMN_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z_][a-z0-9_]*$")
_SCALAR_TYPES: Final[tuple[type[Any], ...]] = (str, int, float, bool, type(None))


def _validate_text(value: Any, field: str, pattern: re.Pattern[str] = _IDENTIFIER) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AuthorityError(f"{field} must be a bounded opaque reference")
    if any(ord(char) < 0x20 for char in value):
        raise AuthorityError(f"{field} contains a control character")
    return value


def validate_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise AuthorityError(f"{field} must be a sha256 digest")
    return value


def validate_ref(value: Any, field: str) -> str:
    return _validate_text(value, field, _REF)


def _safe_value(value: Any, field: str, depth: int = 0) -> Any:
    if depth > 8:
        raise AuthorityError(f"{field} is too deeply nested")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                raise AuthorityError(f"{field} contains a forbidden field")
            result[key] = _safe_value(child, f"{field}.{key}", depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(child, f"{field}[]", depth + 1) for child in value]
    if isinstance(value, _SCALAR_TYPES):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise AuthorityError(f"{field} must not contain NaN or infinity")
        if isinstance(value, str) and any(ord(char) < 0x20 for char in value):
            raise AuthorityError(f"{field} contains a control character")
        return value
    raise AuthorityError(f"{field} contains an unsupported value")


def safe_metadata(value: Mapping[str, Any], field: str = "metadata") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityError(f"{field} must be an object")
    result = _safe_value(value, field)
    if not isinstance(result, dict):
        raise AuthorityError(f"{field} must be an object")
    return result


def canonical_json(value: Any) -> str:
    """Serialize metadata deterministically without accepting non-finite JSON."""

    return json.dumps(
        _safe_value(value, "record"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def seal(value: Mapping[str, Any], hash_field: str = "content_hash") -> dict[str, Any]:
    payload = dict(value)
    payload.pop(hash_field, None)
    payload[hash_field] = canonical_hash(_safe_value(payload, "record"))
    return payload


def _ensure_sealed(value: Mapping[str, Any], field: str = "content_hash") -> None:
    if field not in value:
        raise AuthorityError(f"{field} is required")
    validate_hash(value[field], field)
    payload = {key: child for key, child in value.items() if key != field}
    if value[field] != canonical_hash(_safe_value(payload, "record")):
        raise AuthorityError(f"{field} does not seal the record")


@dataclass(frozen=True, slots=True)
class AuthorityEvent:
    """One immutable, metadata-only event in the TestWeaver authority log."""

    event_id: str
    aggregate_id: str
    aggregate_type: str
    revision: int
    event_type: str
    actor: str
    idempotency_key: str
    occurred_at: str
    payload: Mapping[str, Any]
    request_hash: str
    run_id: str
    campaign_id: str
    trace_id: str
    provenance: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        aggregate_id: str,
        aggregate_type: str,
        revision: int,
        event_type: str,
        actor: str,
        idempotency_key: str,
        occurred_at: str,
        payload: Mapping[str, Any],
        request_hash: str,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        provenance: str,
    ) -> "AuthorityEvent":
        values = {
            "event_id": event_id,
            "aggregate_id": aggregate_id,
            "aggregate_type": aggregate_type,
            "revision": revision,
            "event_type": event_type,
            "actor": actor,
            "idempotency_key": idempotency_key,
            "occurred_at": occurred_at,
            "payload": dict(payload),
            "request_hash": request_hash,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "provenance": provenance,
        }
        return cls(**values, content_hash=canonical_hash(_safe_value(values, "event")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "event_id": self.event_id,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "revision": self.revision,
            "event_type": self.event_type,
            "actor": self.actor,
            "idempotency_key": self.idempotency_key,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
            "request_hash": self.request_hash,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "provenance": self.provenance,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "event_id",
            "aggregate_id",
            "aggregate_type",
            "event_type",
            "actor",
            "idempotency_key",
            "occurred_at",
            "run_id",
            "campaign_id",
            "trace_id",
            "provenance",
        ):
            _validate_text(getattr(self, field), field)
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("revision must be a positive integer")
        validate_hash(self.request_hash, "request_hash")
        safe_metadata(self.payload, "payload")
        _ensure_sealed(self.as_dict(), "content_hash")


@dataclass(frozen=True, slots=True)
class RecordInsert:
    """One fixed-shape authority insert used by the transaction boundary."""

    table: str
    identity_column: str
    identity_value: str
    content_hash: str
    columns: tuple[str, ...]
    values: tuple[Any, ...]


class AuthorityStore:
    """Small append-only repository over a PostgreSQL-compatible DB-API conn.

    SQLite is accepted only for deterministic local contract tests.  Production
    callers provide a PostgreSQL connection; this class never opens one itself.
    """

    def __init__(self, connection: Any):
        if connection is None or not hasattr(connection, "cursor"):
            raise AuthorityError("a DB-API connection is required")
        self.connection = connection
        self._sqlite = connection.__class__.__module__.startswith("sqlite3")

    @classmethod
    def from_sqlite_memory(cls) -> "AuthorityStore":
        import sqlite3

        connection = sqlite3.connect(":memory:")
        store = cls(connection)
        store.initialize()
        return store

    def initialize(self) -> None:
        schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
        if self._sqlite:
            self.connection.executescript(schema)
            self.connection.commit()
            return
        cursor = self.connection.cursor()
        try:
            for statement in schema.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            self.connection.commit()
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit one logical batch once, rolling the whole batch back on error."""

        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _query(self, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(self._adapt_query(query), tuple(params))
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _write(self, query: str, params: Sequence[Any] = (), *, commit: bool = True) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(self._adapt_query(query), tuple(params))
            rowcount = cursor.rowcount
            if commit:
                self.connection.commit()
            return rowcount
        except Exception:
            if commit:
                self.connection.rollback()
            raise
        finally:
            cursor.close()

    def _adapt_query(self, query: str) -> str:
        return query if self._sqlite else query.replace("?", "%s")

    def _insert_once(
        self,
        *,
        table: str,
        identity_column: str,
        identity_value: str,
        hash_column: str,
        hash_value: str,
        columns: Sequence[str],
        values: Sequence[Any],
        commit: bool = True,
    ) -> bool:
        if table not in _AUTHORITY_TABLES:
            raise AuthorityError("writes are limited to authority tables")
        if not _COLUMN_NAME.fullmatch(identity_column) or not _COLUMN_NAME.fullmatch(hash_column):
            raise AuthorityError("invalid authority identity column")
        if not columns or len(columns) != len(values) or len(set(columns)) != len(columns):
            raise AuthorityError("authority insert columns and values do not match")
        if not all(_COLUMN_NAME.fullmatch(column) for column in columns):
            raise AuthorityError("invalid authority insert column")
        if identity_column not in columns or hash_column not in columns:
            raise AuthorityError("authority identity and hash columns must be inserted")
        validate_ref(identity_value, identity_column)
        validate_hash(hash_value, hash_column)
        existing = self._query(
            f"SELECT {hash_column} FROM {table} WHERE {identity_column} = ?",
            (identity_value,),
        )
        if existing:
            if existing[0][0] == hash_value:
                return False
            raise AuthorityConflict(f"{identity_column} is already bound to different content")
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(columns)
        inserted = self._write(
            f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            values,
            commit=commit,
        )
        if inserted:
            return True
        existing = self._query(
            f"SELECT {hash_column} FROM {table} WHERE {identity_column} = ?",
            (identity_value,),
        )
        if existing and existing[0][0] == hash_value:
            return False
        raise AuthorityConflict(f"{identity_column} is already bound to different content")

    def append_event(self, event: AuthorityEvent) -> bool:
        event.validate()
        existing_event = self._query(
            "SELECT content_hash FROM tw_authority_events WHERE event_id = ?",
            (event.event_id,),
        )
        if existing_event:
            if existing_event[0][0] == event.content_hash:
                return False
            raise AuthorityConflict("event_id is already bound to different content")
        existing_idempotency = self._query(
            "SELECT content_hash FROM tw_authority_events WHERE idempotency_key = ?",
            (event.idempotency_key,),
        )
        if existing_idempotency:
            if existing_idempotency[0][0] == event.content_hash:
                return False
            raise AuthorityConflict("idempotency_key is already bound to different content")
        existing_revision = self._query(
            "SELECT revision FROM tw_authority_events WHERE aggregate_id = ? "
            "ORDER BY revision DESC LIMIT 1",
            (event.aggregate_id,),
        )
        if existing_revision and event.revision != existing_revision[0][0] + 1:
            raise AuthorityError("event revision must advance the aggregate by one")
        if not existing_revision and event.revision != 1:
            raise AuthorityError("the first event revision must be one")
        return self._insert_once(
            table="tw_authority_events",
            identity_column="idempotency_key",
            identity_value=event.idempotency_key,
            hash_column="content_hash",
            hash_value=event.content_hash,
            columns=(
                "event_id",
                "aggregate_id",
                "aggregate_type",
                "revision",
                "event_type",
                "actor",
                "idempotency_key",
                "occurred_at",
                "payload_json",
                "request_hash",
                "run_id",
                "campaign_id",
                "trace_id",
                "provenance",
                "content_hash",
            ),
            values=(
                event.event_id,
                event.aggregate_id,
                event.aggregate_type,
                event.revision,
                event.event_type,
                event.actor,
                event.idempotency_key,
                event.occurred_at,
                canonical_json(event.payload),
                event.request_hash,
                event.run_id,
                event.campaign_id,
                event.trace_id,
                event.provenance,
                event.content_hash,
            ),
        )

    def read_events(
        self,
        *,
        run_id: str | None = None,
        campaign_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[AuthorityEvent, ...]:
        clauses: list[str] = []
        params: list[str] = []
        for field, value in (("run_id", run_id), ("campaign_id", campaign_id), ("trace_id", trace_id)):
            if value is not None:
                validate_ref(value, field)
                clauses.append(f"{field} = ?")
                params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(
            "SELECT event_id, aggregate_id, aggregate_type, revision, event_type, actor, "
            "idempotency_key, occurred_at, payload_json, request_hash, run_id, campaign_id, "
            f"trace_id, provenance, content_hash FROM tw_authority_events{where} "
            "ORDER BY revision, event_id",
            params,
        )
        result: list[AuthorityEvent] = []
        for row in rows:
            payload = json.loads(row[8])
            result.append(
                AuthorityEvent(
                    event_id=row[0],
                    aggregate_id=row[1],
                    aggregate_type=row[2],
                    revision=row[3],
                    event_type=row[4],
                    actor=row[5],
                    idempotency_key=row[6],
                    occurred_at=row[7],
                    payload=payload,
                    request_hash=row[9],
                    run_id=row[10],
                    campaign_id=row[11],
                    trace_id=row[12],
                    provenance=row[13],
                    content_hash=row[14],
                )
            )
        return tuple(result)

    def append_record(
        self,
        *,
        table: str,
        identity_column: str,
        identity_value: str,
        content_hash: str,
        columns: Sequence[str],
        values: Sequence[Any],
    ) -> bool:
        """Insert one validated record; callers supply only fixed module SQL."""

        return self.append_records(
            (
                RecordInsert(
                    table=table,
                    identity_column=identity_column,
                    identity_value=identity_value,
                    content_hash=content_hash,
                    columns=tuple(columns),
                    values=tuple(values),
                ),
            )
        )[0]

    def append_records(self, records: Sequence[RecordInsert]) -> tuple[bool, ...]:
        """Append a batch atomically while preserving per-record idempotence."""

        batch = tuple(records)
        if not batch:
            return ()
        for record in batch:
            if not isinstance(record, RecordInsert):
                raise AuthorityError("authority batch contains an invalid insert")
            self._validate_insert(record)
        with self.transaction():
            return tuple(
                self._insert_once(
                    table=record.table,
                    identity_column=record.identity_column,
                    identity_value=record.identity_value,
                    hash_column="content_hash",
                    hash_value=record.content_hash,
                    columns=record.columns,
                    values=record.values,
                    commit=False,
                )
                for record in batch
            )

    def _validate_insert(self, record: RecordInsert) -> None:
        if record.table not in _AUTHORITY_TABLES:
            raise AuthorityError("writes are limited to authority tables")
        if not _COLUMN_NAME.fullmatch(record.identity_column):
            raise AuthorityError("invalid authority identity column")
        if not record.columns or len(record.columns) != len(record.values):
            raise AuthorityError("authority insert columns and values do not match")
        if len(set(record.columns)) != len(record.columns) or not all(
            _COLUMN_NAME.fullmatch(column) for column in record.columns
        ):
            raise AuthorityError("invalid authority insert column")
        if record.identity_column not in record.columns or "content_hash" not in record.columns:
            raise AuthorityError("authority identity and hash columns must be inserted")
        validate_ref(record.identity_value, record.identity_column)
        validate_hash(record.content_hash, "content_hash")

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Read-only query hook used by the thin domain projections."""

        normalized = query.strip()
        if not normalized.casefold().startswith("select") or ";" in normalized:
            raise AuthorityError("authority read hook accepts SELECT only")
        tables = _TABLE_REFERENCE.findall(normalized)
        if not tables or any(table.casefold() not in _AUTHORITY_TABLES for table in tables):
            raise AuthorityError("authority read hook is limited to authority tables")
        return self._query(query, params)


PostgresAuthorityStore = AuthorityStore


__all__ = [
    "AuthorityConflict",
    "AuthorityError",
    "AuthorityEvent",
    "AuthorityStore",
    "PostgresAuthorityStore",
    "RecordInsert",
    "canonical_json",
    "digest_bytes",
    "safe_metadata",
    "seal",
    "validate_hash",
    "validate_ref",
]
