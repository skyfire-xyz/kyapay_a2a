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

from datetime import datetime, timedelta, timezone

import pytest

from kyapay_a2a.rails.nano import (
    AMOUNT_TAG_SPAN,
    NanoPaymentResult,
    NanoQuote,
    NanoRail,
    PaymentNotConfirmed,
    create_nano_payment_requirement,
    usd_to_raw,
)

DEST = "nano_1exampleaddress"


def test_nano_quote_is_feeless_and_fast():
    """Nano should quote a zero fee and sub-second finality."""
    rail = NanoRail()
    quote = rail.quote(1.00)
    assert isinstance(quote, NanoQuote)
    assert quote.rail == "nano-xno"
    assert quote.fee_usd == 0.0
    assert quote.finality_s < 1.0


def test_unconfigured_rail_fails_closed():
    """A NanoRail without an rpc must never report a payment as settled."""
    rail = NanoRail()
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(
            "deadbeef",
            destination=DEST,
            amount_raw="1000000000000000000000000",
        )
    with pytest.raises(PaymentNotConfirmed):
        # No block hash -> nothing could have been verified as settled.
        rail.pay(destination=DEST, amount_raw="1000000000000000000000000")


AMOUNT = "1000000000000000000000000"


def block_info(amount=AMOUNT, destination=DEST, confirmed="true", subtype="send"):
    """A block_info reply shaped like the real Nano RPC for a state send."""
    reply = {
        "amount": amount,
        "confirmed": confirmed,
        "subtype": subtype,
        "contents": {"type": "state", "account": "nano_1buyer"},
    }
    if destination is not None:
        reply["contents"]["link_as_account"] = destination
    return reply


def test_verify_confirms_a_matching_block():
    """A confirmed send block for the exact amount/destination settles."""

    def fake_rpc(request):
        assert request["action"] == "block_info"
        return block_info()

    rail = NanoRail(rpc=fake_rpc)
    result = rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)
    assert isinstance(result, NanoPaymentResult)
    assert result.settled is True
    assert result.rail == "nano-xno"
    assert result.block_hash == "deadbeef"
    assert result.amount_raw == AMOUNT


def test_legacy_send_block_uses_destination_field():
    """A legacy send block names its recipient in contents.destination."""

    def fake_rpc(request):
        return {
            "amount": AMOUNT,
            "confirmed": "true",
            "contents": {"type": "send", "destination": DEST},
        }

    assert (
        NanoRail(rpc=fake_rpc)
        .verify("abc", destination=DEST, amount_raw=AMOUNT)
        .settled
    )


def test_amount_is_read_from_top_level_not_contents():
    """contents.amount is not where block_info reports the transferred amount."""

    def fake_rpc(request):
        reply = block_info(amount=None)
        del reply["amount"]
        reply["contents"]["amount"] = AMOUNT
        return reply

    with pytest.raises(PaymentNotConfirmed):
        NanoRail(rpc=fake_rpc).verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


@pytest.mark.parametrize("confirmed", ["false", False, None, ""])
def test_unconfirmed_block_fails_closed(confirmed):
    """Only an affirmative confirmation settles."""

    def fake_rpc(request):
        reply = block_info(confirmed=confirmed)
        if confirmed is None:
            del reply["confirmed"]
        return reply

    with pytest.raises(PaymentNotConfirmed):
        NanoRail(rpc=fake_rpc).verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_non_send_block_fails_closed():
    """A receive (or any non-send) block is not a payment."""
    rail = NanoRail(rpc=lambda request: block_info(subtype="receive"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_amount_mismatch_fails_closed():
    """A block whose amount differs from the advertised price must not settle."""
    rail = NanoRail(rpc=lambda request: block_info(amount="500000000000000000000000"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_destination_mismatch_fails_closed():
    """A block sent to the wrong address must not settle."""
    rail = NanoRail(rpc=lambda request: block_info(destination="nano_1someoneelse"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_missing_destination_fails_closed():
    """A block with no recipient field must not settle for any address."""
    rail = NanoRail(rpc=lambda request: block_info(destination=None))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_block_hash_settles_only_once():
    """One immutable block pays for one delivery: a replay is refused."""
    rail = NanoRail(rpc=lambda request: block_info())
    assert rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT).settled
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_custom_claim_is_consulted():
    """A shared-storage claim can refuse a hash another process consumed."""
    rail = NanoRail(rpc=lambda request: block_info(), claim=lambda block_hash: False)
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)


def test_failed_verification_does_not_consume_the_hash():
    """A rejected block leaves the hash usable for a corrected retry."""
    replies = [block_info(confirmed="false"), block_info()]
    rail = NanoRail(rpc=lambda request: replies.pop(0))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT)
    assert rail.verify("deadbeef", destination=DEST, amount_raw=AMOUNT).settled


def test_pay_requires_a_block_hash():
    """pay() with no buyer block hash fails closed rather than settle."""
    rail = NanoRail(rpc=lambda request: block_info(amount="1"))
    with pytest.raises(PaymentNotConfirmed):
        rail.pay(destination=DEST, amount_raw="1")


def test_rail_rate_drives_requirement_amount():
    """The rail's own xno_usd converts the advertised price."""
    rail = NanoRail(xno_usd="2.0")
    assert rail.amount_raw_for("1.00") == str(10**30 // 2)
    req = rail.requirement(price_usd="1.00", resource="/r", nano_address=DEST)
    base = 10**30 // 2
    assert base < int(req["amount_raw"]) < base + AMOUNT_TAG_SPAN


def test_usd_to_raw_conversion():
    """USD converts to an exact raw amount for the XNO/USD rate."""
    # $1.00 at XNO=$1.00 is exactly 10^30 raw.
    assert usd_to_raw("1.00", "1.0") == str(10**30)
    # $0.01 at XNO=$1.00 is 10^28 raw.
    assert usd_to_raw("0.01", "1.0") == str(10**28)
    # Rounds DOWN to whole raw, as documented: $1 at XNO=$3 is 333...3 raw.
    assert usd_to_raw("1", "3") == "3" * 30


@pytest.mark.parametrize(
    "price", ["0", "-1", "0.0000000000000000000000000000009", "NaN", "abc"]
)
def test_usd_to_raw_rejects_unpayable_prices(price):
    """Non-positive, sub-raw and non-numeric prices are refused, not settled."""
    with pytest.raises(ValueError):
        usd_to_raw(price, "1")
    with pytest.raises(ValueError):
        create_nano_payment_requirement(price, "/r", DEST)


def test_requirement_rejects_non_positive_expiry():
    with pytest.raises(ValueError):
        create_nano_payment_requirement("1", "/r", DEST, expires_in_seconds=-5)


def test_create_nano_payment_requirement_binds_amount():
    """The requirement should carry the exact raw amount for the price."""
    requirement = create_nano_payment_requirement(
        price_usd="0.01",
        resource="/api/service",
        nano_address=DEST,
        xno_usd="1.0",
    )
    assert requirement["rail"] == "nano-xno"
    assert requirement["price_usd"] == "0.01"
    assert 10**28 < int(requirement["amount_raw"]) < 10**28 + AMOUNT_TAG_SPAN
    assert len(requirement["requirement_id"]) == 32
    assert requirement["nano_address"] == DEST
    assert requirement["resource"] == "/api/service"
    assert requirement["expires_at"] is None


def ledger(*blocks):
    """An rpc whose ledger holds the given {hash: amount} sends to DEST."""
    amounts = dict(blocks)

    def rpc(request):
        amount = amounts.get(request["hash"])
        return block_info(amount=amount) if amount else {"error": "block not found"}

    return rpc


def test_requirements_get_distinct_amounts_and_ids():
    """Two requirements for the same price never share an amount or id."""
    rail = NanoRail()
    reqs = [rail.requirement("1.00", "/r", DEST) for _ in range(20)]
    assert len({r["amount_raw"] for r in reqs}) == 20
    assert len({r["requirement_id"] for r in reqs}) == 20


def test_settle_confirms_its_own_requirement():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    rail._rpc = ledger(("h1", req["amount_raw"]))
    result = rail.settle(req, "h1")
    assert result.settled and result.amount_raw == req["amount_raw"]


def test_block_for_one_requirement_does_not_settle_another():
    """A payment observed on the public ledger cannot be claimed for another
    requirement at the same price."""
    rail = NanoRail()
    paid = rail.requirement("1.00", "/r", DEST)
    other = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger(("h1", paid["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(other, "h1")
    assert rail.settle(paid, "h1").settled


def test_requirement_settles_only_once():
    """A second block for an already-settled requirement delivers nothing."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger(("h1", req["amount_raw"]), ("h2", req["amount_raw"]))
    assert rail.settle(req, "h1").settled
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(req, "h2")


def test_expired_requirement_is_refused():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    rail._rpc = ledger(("h1", req["amount_raw"]))
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.settle(req, "h1", now=later)
    # Refusing an expired requirement must not consume the block.
    assert rail.settle(req, "h1").settled


def test_pay_with_requirement_enforces_expiry_and_match():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    req_expired = dict(req, expires_at="2000-01-01T00:00:00+00:00")
    rail._rpc = ledger(("h1", req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.pay(DEST, req["amount_raw"], "h1", requirement=req_expired)
    with pytest.raises(PaymentNotConfirmed):
        rail.pay(DEST, "1", "h1", requirement=req)
    assert rail.pay(DEST, req["amount_raw"], "h1", requirement=req).settled


@pytest.mark.parametrize(
    "broken",
    [{"rail": "skyfire-usd"}, {"requirement_id": ""}, {"expires_at": "soon"}],
)
def test_malformed_requirement_fails_closed(broken):
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger(("h1", req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(dict(req, **broken), "h1")
