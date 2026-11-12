from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Iterable

from .rules import NamespaceSpec

B32_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
FAKE_SURNAMES = [
    "苏", "沈", "韩", "顾", "陆", "叶", "程", "秦", "许", "何",
    "罗", "高", "梁", "宋", "唐", "邓", "冯", "曹", "彭", "曾",
    "肖", "田", "董", "袁", "潘", "蒋", "蔡", "余", "杜", "魏",
]
FAKE_GIVEN_CHARS = [
    "安", "宁", "远", "知", "清", "和", "言", "舟", "川", "岚",
    "初", "晚", "星", "野", "云", "舒", "诚", "嘉", "若", "沐",
    "简", "澄", "晏", "乔", "砚", "嘉", "禾", "序", "临", "望",
    "白", "苓", "南", "亭", "青", "岚", "书", "亦", "向", "闻",
]

MAX_ALLOCATION_ATTEMPTS = 4096


class AllocationError(RuntimeError):
    pass


@dataclass
class AllocationRow:
    namespace: str
    tenant_id: str
    identity_key: str
    raw_key: str
    fake_value: str


@dataclass
class AllocationStats:
    namespace: str
    kind: str
    values: int = 0
    collisions: int = 0
    residual_avoided: int = 0
    max_attempts: int = 1
    tenants: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "kind": self.kind,
            "values": self.values,
            "collisions": self.collisions,
            "residual_avoided": self.residual_avoided,
            "max_attempts": self.max_attempts,
            "tenants": self.tenants,
        }


def _deterministic_bytes(secret: str, parts: Iterable[str], length: int) -> bytes:
    payload_parts = [part for part in parts]
    output = bytearray()
    counter = 0
    while len(output) < length:
        message = "\x1f".join(payload_parts + [str(counter)])
        output.extend(
            hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
        )
        counter += 1
    return bytes(output[:length])


def _candidate(
    spec: NamespaceSpec,
    secret: str,
    rule_version: str,
    rule_hash: str,
    tenant: str,
    identity: str,
    raw: str,
    attempt: int,
) -> str:
    prefix_parts = [
        "maskflow",
        rule_version,
        rule_hash,
        spec.kind,
        spec.namespace,
        tenant,
        identity,
        raw,
        str(attempt),
    ]

    if spec.kind == "surrogate_id":
        hash_length = spec.max_length - len(spec.prefix)
        data = _deterministic_bytes(secret, prefix_parts, hash_length)
        return spec.prefix + "".join(B32_ALPHABET[byte % len(B32_ALPHABET)] for byte in data)

    if spec.kind == "fake_phone":
        target_length = spec.max_length
        data = _deterministic_bytes(secret, prefix_parts, target_length)
        prefixes = list(spec.prefixes)
        prefix = prefixes[data[0] % len(prefixes)]
        remaining = target_length - len(prefix)
        digits = "".join(str(byte % 10) for byte in data[1 : 1 + remaining])
        return prefix + digits

    if spec.kind == "fake_email":
        local_length = spec.max_length - len(spec.domain) - 1
        data = _deterministic_bytes(secret, prefix_parts, local_length)
        if local_length == 1:
            local = "m"
        else:
            local = "m" + "".join(
                EMAIL_ALPHABET[byte % len(EMAIL_ALPHABET)] for byte in data[1:]
            )
        return f"{local}@{spec.domain}"

    if spec.kind == "fake_name":
        data = _deterministic_bytes(secret, prefix_parts, 4)
        surname = FAKE_SURNAMES[data[0] % len(FAKE_SURNAMES)]
        if spec.max_length <= 1:
            return surname
        given_count = 1 if spec.max_length == 2 else 2
        given = "".join(
            FAKE_GIVEN_CHARS[data[index + 1] % len(FAKE_GIVEN_CHARS)]
            for index in range(given_count)
        )
        return surname + given

    raise AllocationError(f"unsupported namespace kind {spec.kind}")


def allocate_namespace(
    spec: NamespaceSpec,
    keys: Iterable[tuple[str, str, str]],
    banned_values: Iterable[str],
    secret: str,
    rule_version: str,
    rule_hash: str,
    max_attempts: int = MAX_ALLOCATION_ATTEMPTS,
) -> tuple[list[AllocationRow], AllocationStats]:
    """Allocate deterministic fake values.

    Keys are ``(tenant_id, identity_key, raw_key)``. Sorting the keys makes collision
    resolution independent of source row order. Original values are pre-seeded as
    banned so a generated value can never equal an original sensitive value.
    """
    banned = {value for value in banned_values if value != ""}
    allocated: set[str] = set()
    rows: list[AllocationRow] = []
    stats = AllocationStats(namespace=spec.namespace, kind=spec.kind)

    for tenant, identity, raw in sorted(keys, key=lambda item: (item[0], item[1], item[2])):
        attempt = 0
        while True:
            candidate = _candidate(
                spec, secret, rule_version, rule_hash, tenant, identity, raw, attempt
            )
            if len(candidate) > spec.max_length:
                raise AllocationError(
                    f"{spec.namespace}: generated value exceeds max_length "
                    f"({len(candidate)} > {spec.max_length})"
                )
            if candidate not in banned and candidate not in allocated:
                break
            if candidate in banned:
                stats.residual_avoided += 1
                tenant_stats = stats.tenants.setdefault(
                    tenant, {"values": 0, "collisions": 0, "residual_avoided": 0}
                )
                tenant_stats["residual_avoided"] += 1
            else:
                stats.collisions += 1
                tenant_stats = stats.tenants.setdefault(
                    tenant, {"values": 0, "collisions": 0, "residual_avoided": 0}
                )
                tenant_stats["collisions"] += 1
            attempt += 1
            if attempt >= max_attempts:
                raise AllocationError(
                    f"{spec.namespace}/{tenant}: exhausted {max_attempts} attempts "
                    "while resolving collisions; increase max_length or reduce data volume"
                )

        allocated.add(candidate)
        stats.values += 1
        stats.max_attempts = max(stats.max_attempts, attempt + 1)
        tenant_stats = stats.tenants.setdefault(
            tenant, {"values": 0, "collisions": 0, "residual_avoided": 0}
        )
        tenant_stats["values"] += 1
        rows.append(
            AllocationRow(
                namespace=spec.namespace,
                tenant_id=tenant,
                identity_key=identity,
                raw_key=raw,
                fake_value=candidate,
            )
        )

    return rows, stats


def date_offset(
    secret: str,
    rule_version: str,
    rule_hash: str,
    tenant: str,
    identity: str,
    min_days: int,
    max_days: int,
) -> int:
    span = max_days - min_days + 1
    if span <= 0:
        raise AllocationError("date_shift range is empty")
    data = _deterministic_bytes(
        secret,
        ["maskflow", rule_version, rule_hash, "date_shift", tenant, identity, "0"],
        8,
    )
    return min_days + int.from_bytes(data, "big") % span
