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
"""Tests for the Nano (XNO) settlement rail."""

from kyapay_a2a.rails.nano import (
    NanoPaymentResult,
    NanoQuote,
    NanoRail,
    create_nano_payment_requirement,
)


def test_nano_quote_is_feeless_and_fast():
    """Nano should quote a zero fee and sub-second finality."""
    rail = NanoRail()
    quote = rail.quote(1.00)
    assert isinstance(quote, NanoQuote)
    assert quote.rail == "nano-xno"
    assert quote.fee_usd == 0.0
    assert quote.finality_s < 1.0


def test_nano_pay_settles_via_rpc_seam():
    """NanoRail.pay should submit a send block and return the hash."""
    calls = {}

    def fake_rpc(request):
        calls["action"] = request.get("action")
        calls["subtype"] = request.get("subtype")
        return {"block": "0xabc123"}

    rail = NanoRail(rpc=fake_rpc)
    result = rail.pay(destination="nano_1exampleaddress", amount_raw="1000000")
    assert isinstance(result, NanoPaymentResult)
    assert result.settled is True
    assert result.rail == "nano-xno"
    assert result.block_hash == "0xabc123"
    assert calls["action"] == "process"
    assert calls["subtype"] == "send"


def test_create_nano_payment_requirement_shape():
    """A Nano payment requirement should mirror the rails format."""
    requirement = create_nano_payment_requirement(
        price_usd="0.01",
        resource="/api/service",
        nano_address="nano_1exampleaddress",
    )
    assert requirement["rail"] == "nano-xno"
    assert requirement["price_usd"] == "0.01"
    assert requirement["nano_address"] == "nano_1exampleaddress"
    assert requirement["resource"] == "/api/service"
    assert requirement["expires_at"] is None
