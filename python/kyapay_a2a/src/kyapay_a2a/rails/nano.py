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
alternative: a merchant can publish a Nano receive address, a client pays by
sending a Nano block directly to that address (feeless, sub-second finality,
self-custodial — no freezeable stablecoin, no per-tx gas), and the merchant
confirms the spend block with a Nano RPC.

No wallet and no keys are required to run the shipped example or tests: payment
goes through a pluggable ``rpc`` seam, which the example and tests supply as a
local stub. To go live, point ``rpc`` at a real Nano RPC (e.g. rpc.nano.to) or
wrap an existing Nano x402 client (e.g. ``x402nano-exact`` / ``feeless402``),
which this rail reuses rather than rebuilding.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


def _default_send_block(rpc: Callable[..., Any], account: str, amount_raw: str) -> str:
    """Submit a Nano ``send`` block via the ``process`` RPC action.

    ``rpc`` is any callable that accepts an RPC request dict and returns the
    JSON-RPC response dict (``{"block": "<hash>"}`` on success). The shipped
    stub and tests provide this; a real integrations passes
    ``rpc.nano.to``/nanocurrency-python or an existing Nano x402 helper.
    """
    response = rpc(
        {
            "action": "process",
            "json_block": "true",
            "subtype": "send",
            "block": {
                "type": "send",
                "account": account,
                "destination": account,  # replaced by the merchant address below
                "balance": "0",
                "amount": amount_raw,
            },
        }
    )
    return response.get("block", "")


@dataclass
class NanoQuote:
    """A quote for settling a payment on the Nano rail."""

    rail: str = "nano-xno"
    fee_usd: float = 0.0
    finality_s: float = 0.3


@dataclass
class NanoPaymentResult:
    """The result of settling a payment on the Nano rail."""

    settled: bool
    rail: str = "nano-xno"
    block_hash: str = ""
    fee_usd: float = 0.0
    finality_s: float = 0.3
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NanoRail:
    """A minimal Nano (XNO) settlement rail.

    The rail is deliberately thin: ``quote()`` reports the network's honest
    properties (zero fee, sub-second finality) and ``pay()`` settles a spend
    block through the injected ``rpc`` seam. It mirrors the shape of the
    ``PaymentRail`` interface so a merchant can offer both Skyfire-ledger and
    peer-to-peer Nano settlement behind one contract.
    """

    name = "nano-xno"

    def __init__(self, rpc: Callable[..., Any] | None = None) -> None:
        """Build a Nano rail.

        Args:
            rpc: JSON-RPC callable for Nano's ``process`` action. Defaults to a
                stub that reports a deterministic fake block hash, so tests and
                the example run with no wallet and no keys.
        """
        self._rpc = rpc or self._stub_process

    @staticmethod
    def _stub_process(request: dict[str, Any]) -> dict[str, Any]:
        """A local send-block stub - never touches the live network."""
        return {"block": "0xnanostub"}

    def quote(self, amount_usd: float) -> NanoQuote:
        """Quote the fee and finality for a ``amount_usd`` payment on Nano.

        Nano charges no transaction fee and confirms in well under a second,
        so the quote is flat regardless of amount.
        """
        return NanoQuote(rail=self.name, fee_usd=0.0, finality_s=0.3)

    def pay(self, destination: str, amount_raw: str) -> NanoPaymentResult:
        """Submit a Nano spend block to ``destination``.

        Args:
            destination: the merchant's Nano (XNO) receive address
            amount_raw: the raw amount to send (as a decimal string)

        Returns:
            A ``NanoPaymentResult`` with the submitted block hash.
        """
        block_hash = _default_send_block(self._rpc, destination, amount_raw)
        return NanoPaymentResult(
            settled=True,
            rail=self.name,
            block_hash=block_hash,
            fee_usd=0.0,
            finality_s=0.3,
        )


def create_nano_payment_requirement(
    price_usd: str,
    resource: str,
    nano_address: str,
    description: str = "Payment required for this service (Nano XNO rail)",
    expires_in_seconds: int | None = None,
) -> dict[str, Any]:
    """Create a Nano-payment requirement mirroring ``create_payment_requirements``.

    This is the merchant-side counterpart for a seller that wants to accept
    Nano in addition to (or instead of) a Skyfire token. It returns a plain
    dict so it can be attached to a ``KyaPayMetadata`` message without changing
    the core protocol types.

    Args:
        price_usd: US-dollar price as a decimal string (e.g. ``"0.01"``)
        resource: resource identifier (e.g. ``"/api/service"``)
        nano_address: the merchant's Nano (XNO) receive address
        description: human-readable description
        expires_in_seconds: optional payment window

    Returns:
        A dict describing the Nano payment requirement.
    """
    expires_at = None
    if expires_in_seconds:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        ).isoformat()

    return {
        "rail": "nano-xno",
        "price_usd": price_usd,
        "resource": resource,
        "nano_address": nano_address,
        "description": description,
        "expires_at": expires_at,
    }
