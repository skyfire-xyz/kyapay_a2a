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

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
from threading import Lock
from typing import Any

# Nano has 10^30 raw per whole XNO.
RAWS_PER_XNO = 10**30

# Each requirement adds a random tag below this many raw to its amount, so a
# block paid for one requirement cannot match another (10^6 raw is 10^-24 XNO).
AMOUNT_TAG_SPAN = 10**6


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
    called once per successful verification and must return ``True`` only the
    first time a key is claimed (atomically); ``settle`` also claims
    ``"requirement:<requirement_id>"``. The default is an in-process set
    guarded by a lock; a multi-process merchant must pass a claim backed by
    shared storage (e.g. a unique-key insert).
    """

    name = "nano-xno"

    def __init__(
        self,
        rpc: Callable[..., Any] | None = None,
        xno_usd: str | float = "1.0",
        claim: Callable[[str], bool] | None = None,
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
                docstring). Defaults to an in-process set.
        """
        self._rpc = rpc or self._stub_no_confirmation
        self._xno_usd = str(xno_usd)
        self._claimed: set[str] = set()
        self._claim_lock = Lock()
        self._claim = claim or self._claim_in_process

    def _claim_in_process(self, block_hash: str) -> bool:
        with self._claim_lock:
            if block_hash in self._claimed:
                return False
            self._claimed.add(block_hash)
            return True

    def amount_raw_for(self, price_usd: str | float) -> str:
        """The raw amount this rail expects for ``price_usd`` at its rate."""
        return usd_to_raw(price_usd, self._xno_usd)

    def requirement(
        self, price_usd: str, resource: str, nano_address: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Build a payment requirement with this rail's rate, so the advertised
        amount and the amount ``verify`` is later called with share one
        conversion path."""
        return create_nano_payment_requirement(
            price_usd, resource, nano_address, xno_usd=self._xno_usd, **kwargs
        )

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
    ) -> NanoPaymentResult:
        """Confirm a Nano payment block against the merchant's requirement.

        Args:
            block_hash: the hash of the buyer's send block.
            destination: the merchant's Nano (XNO) receive address.
            amount_raw: the raw amount the merchant expects (e.g. from
                ``usd_to_raw`` of the advertised price).

        Returns:
            A ``NanoPaymentResult`` with ``settled=True`` only when the ledger
            shows a confirmed send block whose destination and amount exactly
            match, and the block hash has not been used before.

        Raises:
            PaymentNotConfirmed: when the block does not exist, is not
            confirmed, is not a send, does not match the expected
            amount/destination, or was already consumed.
        """
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
        *,
        now: datetime | None = None,
    ) -> NanoPaymentResult:
        """Settle ``requirement`` with the buyer's block ``block_hash``.

        Args:
            requirement: a dict from ``requirement`` /
                ``create_nano_payment_requirement``.
            block_hash: the hash of the buyer's send block.
            now: the current time (for tests); defaults to UTC now.

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
        expires_at = requirement.get("expires_at")
        if expires_at:
            try:
                deadline = datetime.fromisoformat(str(expires_at))
            except ValueError as exc:
                raise PaymentNotConfirmed(
                    "requirement has an unreadable expires_at"
                ) from exc
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if (now or datetime.now(timezone.utc)) >= deadline:
                raise PaymentNotConfirmed("payment requirement has expired")
        result = self.verify(
            block_hash, destination=str(destination), amount_raw=str(amount_raw)
        )
        if not self._claim(f"requirement:{requirement_id}"):
            raise PaymentNotConfirmed("payment requirement was already settled")
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
        of 1 to ``AMOUNT_TAG_SPAN - 1`` raw. The tag makes the amount unique to
        this requirement, so a block paid for it settles nothing else.

    Raises:
        ValueError: for a non-positive or sub-raw price, or a non-positive
            ``expires_in_seconds``.
    """
    base_raw = int(usd_to_raw(price_usd, xno_usd))
    if expires_in_seconds is not None and expires_in_seconds <= 0:
        raise ValueError("expires_in_seconds must be positive")
    expires_at = None
    if expires_in_seconds:
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
