# Copyright 2026 Skyfire Systems Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A Nano (XNO) settlement rail for the A2A KYAPay flow.

Skyfire's KYAPay today settles entirely on Skyfire's closed US-dollar ledger via
JWT tokens. This module adds an optional **peer-to-peer Nano (XNO) rail** as an
alternative: a merchant publishes a Nano receive address, a client pays by
sending a Nano block directly to that address (feeless, sub-second finality,
self-custodial — no freezeable stablecoin, no per-tx gas), and the merchant
confirms the spend block with a Nano RPC.

This is a **merchant-side verification rail, not a signer**: the buyer signs
and broadcasts the send block; a merchant verifies that a confirmed block
exists on the Nano ledger for the exact amount and destination. There is no
secret material here, so the shipped example and tests run with no wallet and
no keys. Settlement **fails closed**: a payment is only `settled=True` when a
confirmed block for the requested amount and destination is observed; anything
ambiguous is reported as not settled rather than assumed paid.
"""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
from threading import Lock
from typing import Any, Protocol

# Nano has 10^30 raw per whole XNO.
RAWS_PER_XNO = 10**30

# Each requirement adds a random tag below this many raw to its amount
# (10^6 raw is 10^-24 XNO). ``NanoRail.requirement`` re-draws a tag whose
# amount is already outstanding for the same destination.
AMOUNT_TAG_SPAN = 10**6

# How many tags ``NanoRail.requirement`` draws before giving up.
_TAG_ATTEMPTS = 64

# A block's node-reported time may differ a little from this host's clock;
# the issue-time check tolerates this much skew.
BLOCK_CLOCK_SKEW = timedelta(seconds=30)

# A Nano block hash: 32 bytes as 64 hex digits (canonical form is upper case).
_BLOCK_HASH = re.compile(r"[0-9A-F]{64}")


def normalize_block_hash(block_hash: Any) -> str:
    """Return the canonical (stripped, upper-case) form of a Nano block hash.

    Raises:
        PaymentNotConfirmed: when ``block_hash`` is not a string of exactly 64
            hex digits once surrounding whitespace is removed.
    """
    if not isinstance(block_hash, str):
        raise PaymentNotConfirmed("no block hash to verify")
    canonical = block_hash.strip().upper()
    if not _BLOCK_HASH.fullmatch(canonical):
        raise PaymentNotConfirmed("block hash is not 64 hex digits")
    return canonical


def usd_to_raw(price_usd: str | float, xno_usd: str | float) -> str:
    """Convert a US-dollar price to a Nano raw amount as a decimal string.

    Args:
        price_usd: the USD price (``"0.01"`` or ``0.01``).
        xno_usd: the price of one XNO in US dollars.

    Returns:
        The exact raw amount (integer raw units) as a decimal string, computed
        with ``Decimal`` so no floating-point error creeps into the raw count.
        Rounds down to whole raw.

    Raises:
        ValueError: when the price or rate is not a positive number, or the
            price is smaller than one raw at this rate (nothing payable).
    """
    try:
        price = Decimal(str(price_usd))
        rate = Decimal(str(xno_usd))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {price_usd!r} / {xno_usd!r}") from exc
    if not rate.is_finite() or rate <= 0:
        raise ValueError("xno_usd must be positive")
    if not price.is_finite() or price <= 0:
        raise ValueError("price_usd must be positive")
    # Default Decimal precision (28 digits) is too small for 30-decimal raw
    # amounts; multiply before dividing, at a precision that keeps every digit.
    with localcontext() as ctx:
        ctx.prec = 80
        raw = (price * RAWS_PER_XNO / rate).to_integral_value(rounding=ROUND_DOWN)
    if raw <= 0:
        raise ValueError("price_usd is smaller than one raw at this rate")
    return str(int(raw))


class PaymentNotConfirmed(Exception):
    """Raised when a claimed Nano payment cannot be confirmed on the ledger."""


class OutstandingAmounts(Protocol):
    """Where ``NanoRail.requirement`` reserves the amounts it hands out.

    A requirement is bound to its payment only by its exact amount and
    destination, so two open requirements must never share both. Every rail
    (and every process) that issues requirements for one address must use the
    same store; the default (one process-wide ``InMemoryOutstandingAmounts``)
    covers one process only. A shared store is typically a table with a unique key on
    ``(destination, amount_raw)`` whose expired rows are treated as free.
    """

    def reserve(
        self,
        destination: str,
        amount_raw: str,
        requirement_id: str,
        deadline: datetime | None,
    ) -> bool:
        """Atomically reserve ``amount_raw`` at ``destination`` for
        ``requirement_id`` until ``deadline`` (``None``: until released).
        Return ``False`` when an unexpired reservation already holds it."""
        ...

    def release(self, destination: str, amount_raw: str, requirement_id: str) -> None:
        """Free the reservation if ``requirement_id`` still holds it."""
        ...

    def issued_at(
        self, destination: str, amount_raw: str, requirement_id: str
    ) -> datetime | None:
        """When ``requirement_id`` reserved this amount, or ``None`` if it
        does not currently hold it. ``settle`` trusts this record, never the
        requirement dict the caller hands back, so a tampered id, address or
        amount is refused and a block older than the issue is refused."""
        ...


class InMemoryClaims:
    """The default ``claim``: a set of consumed keys guarded by a lock.

    Calling it with a key returns ``True`` the first time and ``False`` after.
    Its scope is the object itself. Every ``NanoRail`` built without ``claim``
    uses one process-wide instance, so rails in one process see each other's
    consumed hashes; rails in separate processes or workers need a ``claim``
    backed by shared storage.
    """

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    def __call__(self, key: str) -> bool:
        with self._lock:
            if key in self._claimed:
                return False
            self._claimed.add(key)
            return True


class InMemoryOutstandingAmounts:
    """The default ``OutstandingAmounts``: a dict guarded by a lock.

    Its scope is the object itself. Every ``NanoRail`` built without
    ``outstanding`` uses one process-wide instance, so rails in one process
    coordinate; separate processes or workers that issue
    requirements for one address must share an ``OutstandingAmounts`` (and a
    ``claim``) backed by shared storage, or each use their own address.
    """

    def __init__(self) -> None:
        # (destination, amount_raw) -> (requirement_id, deadline or None, issued)
        self._entries: dict[tuple[str, str], tuple[str, datetime | None, datetime]] = {}
        self._lock = Lock()

    def reserve(
        self,
        destination: str,
        amount_raw: str,
        requirement_id: str,
        deadline: datetime | None,
    ) -> bool:
        with self._lock:
            now = datetime.now(timezone.utc)
            for held_key, (_, held_deadline, _) in list(self._entries.items()):
                if held_deadline is not None and now >= held_deadline:
                    del self._entries[held_key]
            key = (destination, amount_raw)
            if key in self._entries:
                return False
            self._entries[key] = (requirement_id, deadline, now)
            return True

    def release(self, destination: str, amount_raw: str, requirement_id: str) -> None:
        with self._lock:
            key = (destination, amount_raw)
            held = self._entries.get(key)
            if held is not None and held[0] == requirement_id:
                del self._entries[key]

    def issued_at(
        self, destination: str, amount_raw: str, requirement_id: str
    ) -> datetime | None:
        with self._lock:
            held = self._entries.get((destination, amount_raw))
            if held is None or held[0] != requirement_id:
                return None
            if held[1] is not None and datetime.now(timezone.utc) >= held[1]:
                return None
            return held[2]


# The process-wide default stores. Every ``NanoRail`` built without ``claim``
# (or ``outstanding``) uses these same objects, so rails in one process refuse
# each other's consumed block hashes and settled requirements, and never issue
# the same amount for one address. Workers in separate processes still need
# stores backed by shared storage.
_DEFAULT_CLAIMS = InMemoryClaims()
_DEFAULT_OUTSTANDING = InMemoryOutstandingAmounts()


@dataclass
class NanoQuote:
    """A quote for settling a payment on the Nano rail."""

    rail: str = "nano-xno"
    fee_usd: float = 0.0
    finality_s: float = 0.3


@dataclass
class NanoPaymentResult:
    """The result of verifying a payment on the Nano rail."""

    settled: bool
    rail: str = "nano-xno"
    block_hash: str = ""
    amount_raw: str = ""
    fee_usd: float = 0.0
    finality_s: float = 0.3
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NanoRail:
    """A merchant-side Nano (XNO) settlement rail.

    ``verify`` confirms a payment by reading the Nano ledger: it asks the
    injected ``rpc`` for the ``block_info`` of the hash the buyer supplies and
    only reports ``settled`` when the block's destination and raw amount match
    the merchant's advertised requirement. This **fails closed** — no confirmed
    block, no settlement.

    ``settle`` is the entry point for a requirement built by ``requirement``:
    it refuses an expired requirement, settles each requirement at most once,
    and checks the block against that requirement's own (tagged) amount, so a
    block paid for one requirement cannot be claimed for another. ``verify``
    is the lower-level check against a bare destination and amount.

    ``rpc`` is any callable that accepts an RPC request dict and returns the
    JSON-RPC response dict. A real integration passes rpc.nano.to (or wraps an
    existing Nano x402 client such as ``x402nano-exact`` / ``feeless402``).

    A Nano block is immutable, so one block hash could otherwise authorize
    repeated deliveries. ``verify`` therefore *consumes* the hash: ``claim`` is
    called once per successful verification with the canonical (upper-case)
    hash and must return ``True`` only the first time a key is claimed
    (atomically); ``settle`` also claims ``"requirement:<requirement_id>"``.

    Both defaults (``claim`` and ``outstanding``) are in-memory stores shared
    by every ``NanoRail`` in the process that was built without its own: a
    block consumed by one such rail is refused by the others. That state does
    not leave the process, so rails in separate processes or workers that
    settle payments to one receive address must pass a ``claim`` and an
    ``outstanding`` backed by shared storage (e.g. unique-key inserts), or
    each use their own address; otherwise one payment could settle a
    requirement in each process. A rail given its own store does not consult
    the process-wide default.
    """

    name = "nano-xno"

    def __init__(
        self,
        rpc: Callable[..., Any] | None = None,
        xno_usd: str | float = "1.0",
        claim: Callable[[str], bool] | None = None,
        outstanding: OutstandingAmounts | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Build a Nano rail.

        Args:
            rpc: JSON-RPC callable backing the ``block_info`` read. When
                omitted the rail is built with a stub that reports *no*
                confirmation, so an unconfigured rail never settles a payment
                (fail-closed by default).
            xno_usd: XNO/USD rate used by ``amount_raw_for`` and
                ``requirement`` to convert an advertised USD price to a raw
                amount. Override in production with a live quote.
            claim: atomic "first use" check for a block hash (see class
                docstring). Defaults to the process-wide ``InMemoryClaims``
                shared by every rail built without one.
            outstanding: where ``requirement`` reserves amounts so that no
                two open requirements for one address share an amount.
                Defaults to the process-wide ``InMemoryOutstandingAmounts``
                shared by every rail built without one.
            clock: returns the current UTC time ``settle`` checks expiry
                against. Defaults to the system clock; set it only to test.
        """
        self._rpc = rpc or self._stub_no_confirmation
        self._xno_usd = str(xno_usd)
        self._claim: Callable[[str], bool] = (
            claim if claim is not None else _DEFAULT_CLAIMS
        )
        self._outstanding: OutstandingAmounts = (
            outstanding if outstanding is not None else _DEFAULT_OUTSTANDING
        )
        self._clock: Callable[[], datetime] = clock or (
            lambda: datetime.now(timezone.utc)
        )

    def amount_raw_for(self, price_usd: str | float) -> str:
        """The raw amount this rail expects for ``price_usd`` at its rate."""
        return usd_to_raw(price_usd, self._xno_usd)

    def requirement(
        self, price_usd: str, resource: str, nano_address: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Build a payment requirement with this rail's rate, so the advertised
        amount and the amount ``verify`` is later called with share one
        conversion path.

        The rail reserves each tagged amount in its ``outstanding`` store and
        re-draws the tag on a collision, so no two outstanding requirements
        sharing that store have the same amount and destination. An amount is
        released when its requirement settles or expires; a requirement
        without ``expires_in_seconds`` holds its amount until it settles. With
        the default (process-wide) store this holds only within one process
        (see ``InMemoryOutstandingAmounts``).

        Raises:
            ValueError: as ``create_nano_payment_requirement``, or when no
                free amount was found for this price and destination.
        """
        for _ in range(_TAG_ATTEMPTS):
            req = create_nano_payment_requirement(
                price_usd, resource, nano_address, xno_usd=self._xno_usd, **kwargs
            )
            deadline = (
                datetime.fromisoformat(req["expires_at"])
                if req["expires_at"] is not None
                else None
            )
            if self._outstanding.reserve(
                str(req["nano_address"]),
                str(req["amount_raw"]),
                str(req["requirement_id"]),
                deadline,
            ):
                return req
        raise ValueError("no free amount for this price and destination")

    @staticmethod
    def _stub_no_confirmation(request: dict[str, Any]) -> dict[str, Any]:
        """A local stub that confirms nothing - fails closed, no live network."""
        return {"error": "block unknown"}

    def quote(self, amount_usd: float) -> NanoQuote:
        """Quote the fee and finality for an ``amount_usd`` payment on Nano.

        Nano charges no transaction fee and confirms in well under a second,
        so the quote is flat regardless of amount.
        """
        return NanoQuote(rail=self.name, fee_usd=0.0, finality_s=0.3)

    def _query_block(self, block_hash: str) -> dict[str, Any]:
        """Read the ledger entry for ``block_hash`` via the injected rpc."""
        response = self._rpc(
            {
                "action": "block_info",
                "json_block": "true",
                "hash": block_hash,
            }
        )
        if not isinstance(response, dict) or "error" in response:
            raise PaymentNotConfirmed(f"block_info returned no block: {response!r}")
        # Nano RPC reports confirmation separately, usually as the string
        # "true"/"false". Only an affirmative value counts.
        if str(response.get("confirmed", "")).lower() != "true":
            raise PaymentNotConfirmed("block is not confirmed on the ledger")
        return response

    def verify(
        self,
        block_hash: str,
        *,
        destination: str,
        amount_raw: str,
        not_before: datetime | None = None,
        not_after: datetime | None = None,
    ) -> NanoPaymentResult:
        """Confirm a Nano payment block against the merchant's requirement.

        Args:
            block_hash: the hash of the buyer's send block (64 hex digits;
                case and surrounding whitespace are normalised away, so the
                canonical upper-case form is what is queried and consumed).
            destination: the merchant's Nano (XNO) receive address.
            amount_raw: the raw amount the merchant expects (e.g. from
                ``usd_to_raw`` of the advertised price).
            not_before: when set, the block's own ``local_timestamp`` must be
                at or after this time (less ``BLOCK_CLOCK_SKEW``): a block
                older than the order cannot pay it. ``settle`` passes the
                time the requirement was issued.
            not_after: when set, the block's time must be at or before this
                time (plus the skew): a late block cannot pay an expired
                order. ``settle`` passes the requirement's expiry. A block
                with no usable time is refused whenever either is set.

        Returns:
            A ``NanoPaymentResult`` with ``settled=True`` only when the ledger
            shows a confirmed send block whose destination and amount exactly
            match, and the block hash has not been used before.

        Raises:
            PaymentNotConfirmed: when an argument is empty, ``block_hash`` is
            not 64 hex digits, ``amount_raw`` is not a positive integer, or the block does not exist, is not
            confirmed, is not a send, does not match the expected
            amount/destination, or was already consumed.
        """
        block_hash = normalize_block_hash(block_hash)
        if not isinstance(destination, str) or not destination:
            raise PaymentNotConfirmed("no destination to verify against")
        amount_raw = "" if amount_raw is None else str(amount_raw)
        if not (amount_raw.isascii() and amount_raw.isdigit()) or int(amount_raw) <= 0:
            raise PaymentNotConfirmed(
                f"expected amount is not a positive raw integer: {amount_raw!r}"
            )
        info = self._query_block(block_hash)
        block = info.get("contents")
        if not isinstance(block, dict):
            raise PaymentNotConfirmed("block_info returned no block contents")

        # A state block says "send" in the top-level ``subtype``; a legacy
        # send block says it in ``contents.type``.
        is_send = info.get("subtype") == "send" or block.get("type") == "send"
        if not is_send:
            raise PaymentNotConfirmed("block is not a send")

        # block_info reports the transferred amount at the top level;
        # ``contents`` holds the serialized block (whose ``balance`` is the
        # sender's remaining balance, not the amount sent).
        block_amount = str(info.get("amount", ""))
        if block_amount != str(amount_raw):
            raise PaymentNotConfirmed(
                f"amount mismatch: expected {amount_raw}, found {block_amount or 'none'}"
            )

        if not_before is not None or not_after is not None:
            try:
                block_time = datetime.fromtimestamp(
                    int(str(info.get("local_timestamp", ""))), timezone.utc
                )
            except (ValueError, OverflowError, OSError):
                block_time = None
            if block_time is None or block_time.year < 2015:
                raise PaymentNotConfirmed("block has no usable local_timestamp")
            if not_before is not None and block_time < not_before - BLOCK_CLOCK_SKEW:
                raise PaymentNotConfirmed("block predates the payment requirement")
            if not_after is not None and block_time > not_after + BLOCK_CLOCK_SKEW:
                raise PaymentNotConfirmed(
                    "block was made after the requirement expired"
                )

        # State blocks carry the recipient in link_as_account; legacy send
        # blocks in destination. It must be present and exact.
        block_destination = (
            block.get("link_as_account") or block.get("destination") or ""
        )
        if block_destination != destination:
            raise PaymentNotConfirmed(
                f"destination mismatch: expected {destination}, found {block_destination or 'none'}"
            )

        if not self._claim(block_hash):
            raise PaymentNotConfirmed("block hash already used for a settled payment")
        return NanoPaymentResult(
            settled=True,
            rail=self.name,
            block_hash=block_hash,
            amount_raw=amount_raw,
            fee_usd=0.0,
            finality_s=0.3,
        )

    def settle(
        self,
        requirement: dict[str, Any],
        block_hash: str,
    ) -> NanoPaymentResult:
        """Settle ``requirement`` with the buyer's block ``block_hash``.

        Args:
            requirement: a dict from ``requirement`` /
                ``create_nano_payment_requirement``.
            block_hash: the hash of the buyer's send block.

        Expiry is checked against the rail's ``clock``; a caller cannot pass
        its own time.

        Raises:
            PaymentNotConfirmed: when the requirement is malformed, expired or
            already settled, or ``verify`` refuses the block.
        """
        if not isinstance(requirement, dict) or requirement.get("rail") != self.name:
            raise PaymentNotConfirmed("not a Nano payment requirement")
        requirement_id = requirement.get("requirement_id")
        destination = requirement.get("nano_address")
        amount_raw = requirement.get("amount_raw")
        if not requirement_id or not destination or not amount_raw:
            raise PaymentNotConfirmed(
                "requirement lacks requirement_id, nano_address or amount_raw"
            )
        # Only a missing or ``None`` expires_at means "no expiry". Any other
        # value - including falsy ones such as ``""``, ``0`` or ``False`` - must
        # be an ISO 8601 string, or the requirement is refused.
        expires_at = requirement.get("expires_at")
        if expires_at is not None:
            if not isinstance(expires_at, str):
                raise PaymentNotConfirmed("requirement has an unreadable expires_at")
            try:
                deadline = datetime.fromisoformat(expires_at)
            except ValueError as exc:
                raise PaymentNotConfirmed(
                    "requirement has an unreadable expires_at"
                ) from exc
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if self._clock() >= deadline:
                raise PaymentNotConfirmed("payment requirement has expired")
        # Bind to what THIS store issued, not to the dict the caller returned:
        # the id, address and amount must be a live reservation, and the block
        # must have been made after the requirement was issued (and before it
        # expired), so a late block for an expired order cannot pay a newer one
        # that was handed the same amount.
        issued = getattr(self._outstanding, "issued_at", None)
        issued_at = (
            issued(str(destination), str(amount_raw), str(requirement_id))
            if callable(issued)
            else None
        )
        if issued_at is None:
            raise PaymentNotConfirmed(
                "requirement was not issued by this rail's store (or is released)"
            )
        result = self.verify(
            block_hash,
            destination=str(destination),
            amount_raw=str(amount_raw),
            not_before=issued_at,
            not_after=deadline if expires_at is not None else None,
        )
        if not self._claim(f"requirement:{requirement_id}"):
            raise PaymentNotConfirmed("payment requirement was already settled")
        self._outstanding.release(
            str(destination), str(amount_raw), str(requirement_id)
        )
        return result

    # Pay is intentionally not a signing operation on the merchant side. The
    # buyer broadcasts the send; a merchant only verifies. We keep a thin
    # ``pay`` alias to ``verify`` for callers that already hold the buyer's
    # block hash, so the two words map to one fail-closed settlement.
    def pay(
        self,
        destination: str,
        amount_raw: str,
        block_hash: str | None = None,
        requirement: dict[str, Any] | None = None,
    ) -> NanoPaymentResult:
        """Settle by verifying a buyer's block; fails closed if unconfirmed.

        With ``requirement`` this is ``settle`` (expiry and single use are
        enforced, and ``destination``/``amount_raw`` must match it).
        """
        if not block_hash:
            raise PaymentNotConfirmed("no block hash to verify - nothing was settled")
        if requirement is not None:
            if requirement.get("nano_address") != destination or str(
                requirement.get("amount_raw")
            ) != str(amount_raw):
                raise PaymentNotConfirmed(
                    "destination/amount differ from the requirement"
                )
            return self.settle(requirement, block_hash)
        return self.verify(
            block_hash,
            destination=destination,
            amount_raw=amount_raw,
        )


def create_nano_payment_requirement(
    price_usd: str,
    resource: str,
    nano_address: str,
    xno_usd: str | float = "1.0",
    description: str = "Payment required for this service (Nano XNO rail)",
    expires_in_seconds: int | None = None,
) -> dict[str, Any]:
    """Create a Nano-payment requirement mirroring ``create_payment_requirements``.

    This is the merchant-side counterpart for a seller that wants to accept
    Nano in addition to (or instead of) a Skyfire token. It is deliberately
    not a ``KyaPayRequirements``: that model requires a Skyfire
    ``seller_service_id`` and a token type, which a Nano payment has no use
    for, so the existing token flow cannot consume it and this rail does not
    pretend otherwise. It returns a plain dict that a merchant offers next to
    its ``KyaPayRequirements`` and later passes to ``NanoRail.settle``.

    Args:
        price_usd: US-dollar price as a decimal string (e.g. ``"0.01"``)
        resource: resource identifier (e.g. ``"/api/service"``)
        nano_address: the merchant's Nano (XNO) receive address
        xno_usd: XNO/USD rate used to compute the raw amount
        description: human-readable description
        expires_in_seconds: optional payment window

    Returns:
        A dict describing the Nano payment requirement: a random
        ``requirement_id`` and the exact raw amount the rail will accept
        (``amount_raw``), which is ``usd_to_raw(price_usd)`` plus a random tag
        of 1 to ``AMOUNT_TAG_SPAN - 1`` raw. A bare call does not check for
        collisions with other requirements; ``NanoRail.requirement`` does, so
        that a block paid for one outstanding requirement matches no other.

    Raises:
        ValueError: for a non-positive or sub-raw price, or a non-positive
            ``expires_in_seconds``.
    """
    base_raw = int(usd_to_raw(price_usd, xno_usd))
    if expires_in_seconds is not None and expires_in_seconds <= 0:
        raise ValueError("expires_in_seconds must be positive")
    expires_at = None
    if expires_in_seconds is not None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        ).isoformat()

    return {
        "rail": "nano-xno",
        "price_usd": price_usd,
        "amount_raw": str(base_raw + 1 + secrets.randbelow(AMOUNT_TAG_SPAN - 1)),
        "requirement_id": secrets.token_hex(16),
        "resource": resource,
        "nano_address": nano_address,
        "description": description,
        "expires_at": expires_at,
    }
