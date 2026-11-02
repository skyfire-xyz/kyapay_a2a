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

import time
from datetime import datetime, timedelta, timezone

import pytest

from kyapay_a2a.rails import nano
from kyapay_a2a.rails.nano import (
    AMOUNT_TAG_SPAN,
    InMemoryClaims,
    InMemoryOutstandingAmounts,
    NanoPaymentResult,
    NanoQuote,
    NanoRail,
    PaymentNotConfirmed,
    create_nano_payment_requirement,
    usd_to_raw,
)

DEST = "nano_1exampleaddress"

# Canonical (upper-case, 64 hex digit) Nano block hashes.
H = "DEADBEEF" * 8
H1 = "1" * 64
H2 = "2" * 64
H3 = "ABC" + "0" * 61


@pytest.fixture(autouse=True)
def fresh_default_stores(monkeypatch):
    """Give each test its own process-wide default stores, so tests that reuse
    a block hash or amount do not see one another's claims."""
    monkeypatch.setattr(nano, "_DEFAULT_CLAIMS", InMemoryClaims(), raising=False)
    monkeypatch.setattr(
        nano, "_DEFAULT_OUTSTANDING", InMemoryOutstandingAmounts(), raising=False
    )


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
            H,
            destination=DEST,
            amount_raw="1000000000000000000000000",
        )
    with pytest.raises(PaymentNotConfirmed):
        # No block hash -> nothing could have been verified as settled.
        rail.pay(destination=DEST, amount_raw="1000000000000000000000000")


AMOUNT = "1000000000000000000000000"


def block_info(
    amount=AMOUNT, destination=DEST, confirmed="true", subtype="send", at=None
):
    """A block_info reply shaped like the real Nano RPC for a state send."""
    reply = {
        "amount": amount,
        "confirmed": confirmed,
        "subtype": subtype,
        "local_timestamp": str(int(time.time()) if at is None else at),
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
    result = rail.verify(H, destination=DEST, amount_raw=AMOUNT)
    assert isinstance(result, NanoPaymentResult)
    assert result.settled is True
    assert result.rail == "nano-xno"
    assert result.block_hash == H
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
        NanoRail(rpc=fake_rpc).verify(H3, destination=DEST, amount_raw=AMOUNT).settled
    )


def test_amount_is_read_from_top_level_not_contents():
    """contents.amount is not where block_info reports the transferred amount."""

    def fake_rpc(request):
        reply = block_info(amount=None)
        del reply["amount"]
        reply["contents"]["amount"] = AMOUNT
        return reply

    with pytest.raises(PaymentNotConfirmed):
        NanoRail(rpc=fake_rpc).verify(H, destination=DEST, amount_raw=AMOUNT)


@pytest.mark.parametrize("confirmed", ["false", False, None, ""])
def test_unconfirmed_block_fails_closed(confirmed):
    """Only an affirmative confirmation settles."""

    def fake_rpc(request):
        reply = block_info(confirmed=confirmed)
        if confirmed is None:
            del reply["confirmed"]
        return reply

    with pytest.raises(PaymentNotConfirmed):
        NanoRail(rpc=fake_rpc).verify(H, destination=DEST, amount_raw=AMOUNT)


def test_non_send_block_fails_closed():
    """A receive (or any non-send) block is not a payment."""
    rail = NanoRail(rpc=lambda request: block_info(subtype="receive"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_amount_mismatch_fails_closed():
    """A block whose amount differs from the advertised price must not settle."""
    rail = NanoRail(rpc=lambda request: block_info(amount="500000000000000000000000"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_destination_mismatch_fails_closed():
    """A block sent to the wrong address must not settle."""
    rail = NanoRail(rpc=lambda request: block_info(destination="nano_1someoneelse"))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_missing_destination_fails_closed():
    """A block with no recipient field must not settle for any address."""
    rail = NanoRail(rpc=lambda request: block_info(destination=None))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_block_hash_settles_only_once():
    """One immutable block pays for one delivery: a replay is refused."""
    rail = NanoRail(rpc=lambda request: block_info())
    assert rail.verify(H, destination=DEST, amount_raw=AMOUNT).settled
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_custom_claim_is_consulted():
    """A shared-storage claim can refuse a hash another process consumed."""
    rail = NanoRail(rpc=lambda request: block_info(), claim=lambda block_hash: False)
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_failed_verification_does_not_consume_the_hash():
    """A rejected block leaves the hash usable for a corrected retry."""
    replies = [block_info(confirmed="false"), block_info()]
    rail = NanoRail(rpc=lambda request: replies.pop(0))
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)
    assert rail.verify(H, destination=DEST, amount_raw=AMOUNT).settled


@pytest.mark.parametrize(
    "block_hash, destination, amount_raw",
    [
        ("", DEST, AMOUNT),
        (None, DEST, AMOUNT),
        (H, "", AMOUNT),
        (H, None, AMOUNT),
        (H, DEST, ""),
        (H, DEST, None),
        (H, DEST, "0"),
        (H, DEST, "-1"),
        (H, DEST, "1.5"),
        ("", "", ""),
        ("deadbeef", DEST, AMOUNT),
        ("A" * 63, DEST, AMOUNT),
        ("A" * 65, DEST, AMOUNT),
        ("G" * 64, DEST, AMOUNT),
        ("0x" + "A" * 62, DEST, AMOUNT),
        ("A" * 32 + " " + "A" * 31, DEST, AMOUNT),
        ("\uff21" * 64, DEST, AMOUNT),
        (123, DEST, AMOUNT),
    ],
)
def test_verify_rejects_empty_or_missing_inputs(block_hash, destination, amount_raw):
    """Empty inputs fail closed even if the rpc reply is just as empty."""
    calls = []

    def empty_rpc(request):
        calls.append(request)
        return {"confirmed": "true", "subtype": "send", "contents": {}}

    rail = NanoRail(rpc=empty_rpc)
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(block_hash, destination=destination, amount_raw=amount_raw)
    assert calls == []


@pytest.mark.parametrize(
    "variant", [H.lower(), f"  {H}  ", f"{H}\n", f"\t{H.lower()} ", H.title()]
)
def test_noncanonical_hash_replay_is_refused(variant):
    """A re-cased or padded copy of a consumed hash is the same block."""
    queried = []

    def rpc(request):
        queried.append(request["hash"])
        return block_info()

    rail = NanoRail(rpc=rpc)
    assert rail.verify(H, destination=DEST, amount_raw=AMOUNT).settled
    with pytest.raises(PaymentNotConfirmed, match="already used"):
        rail.verify(variant, destination=DEST, amount_raw=AMOUNT)
    assert queried == [H, H]


def test_noncanonical_hash_is_normalised_before_claim():
    """The first use of a hash is consumed in canonical form, so the
    canonical form is refused afterwards."""
    claimed = []

    def claim(key):
        claimed.append(key)
        return claimed.count(key) == 1

    rail = NanoRail(rpc=lambda request: block_info(), claim=claim)
    result = rail.verify(f" {H.lower()} ", destination=DEST, amount_raw=AMOUNT)
    assert result.block_hash == H
    with pytest.raises(PaymentNotConfirmed):
        rail.verify(H, destination=DEST, amount_raw=AMOUNT)
    assert claimed == [H, H]


def test_settle_refuses_noncanonical_replay_of_a_requirement_block():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    assert rail.settle(req, H1.lower()).settled
    other = dict(req, requirement_id="f" * 32)
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(other, f" {H1} ")


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
    "price", ["0", "-1", "0.0000000000000000000000000000009", "NaN", H3]
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


def test_requirements_get_distinct_amounts_and_ids(monkeypatch):
    """Outstanding requirements for the same price never share an amount or id,
    even when the tag source repeats itself (draws are scripted, not random)."""
    draws = iter([i // 2 for i in range(40)])  # 0, 0, 1, 1, 2, 2, ...
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: next(draws))
    rail = NanoRail()
    reqs = [rail.requirement("1.00", "/r", DEST) for _ in range(20)]
    assert [r["amount_raw"] for r in reqs] == [str(10**30 + 1 + i) for i in range(20)]
    assert len({r["requirement_id"] for r in reqs}) == 20


def test_requirement_redraws_a_colliding_tag(monkeypatch):
    """A tag whose amount is already outstanding is drawn again."""
    draws = iter([7, 7, 7, 9])
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: next(draws))
    rail = NanoRail()
    first = rail.requirement("1.00", "/r", DEST)
    second = rail.requirement("1.00", "/r", DEST)
    assert first["amount_raw"] == str(10**30 + 8)
    assert second["amount_raw"] == str(10**30 + 10)


def test_same_tag_is_allowed_for_another_destination(monkeypatch):
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    rail = NanoRail()
    a = rail.requirement("1.00", "/r", DEST)
    b = rail.requirement("1.00", "/r", "nano_1otheraddress")
    assert a["amount_raw"] == b["amount_raw"]


def test_requirement_gives_up_when_no_amount_is_free(monkeypatch):
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    rail = NanoRail()
    rail.requirement("1.00", "/r", DEST)
    with pytest.raises(ValueError):
        rail.requirement("1.00", "/r", DEST)


def test_settled_and_expired_amounts_are_released(monkeypatch):
    """An amount is reusable once its requirement settles or expires."""
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    store = InMemoryOutstandingAmounts()
    rail = NanoRail(outstanding=store)
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    rail.settle(req, H1)
    again = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    assert again["amount_raw"] == req["amount_raw"]
    with pytest.raises(ValueError):
        rail.requirement("1.00", "/r", DEST)
    key = (DEST, again["amount_raw"])
    store._entries[key] = (
        again["requirement_id"],
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        datetime(1999, 1, 1, tzinfo=timezone.utc),
    )
    assert rail.requirement("1.00", "/r", DEST)["amount_raw"] == req["amount_raw"]


def test_settle_confirms_its_own_requirement():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    rail._rpc = ledger((H1, req["amount_raw"]))
    result = rail.settle(req, H1)
    assert result.settled and result.amount_raw == req["amount_raw"]


def test_block_for_one_requirement_does_not_settle_another():
    """A payment observed on the public ledger cannot be claimed for another
    requirement at the same price."""
    rail = NanoRail()
    paid = rail.requirement("1.00", "/r", DEST)
    other = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, paid["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(other, H1)
    assert rail.settle(paid, H1).settled


def test_requirement_settles_only_once():
    """A second block for an already-settled requirement delivers nothing."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]), (H2, req["amount_raw"]))
    assert rail.settle(req, H1).settled
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(req, H2)


def test_expired_requirement_is_refused():
    start = datetime.now(timezone.utc)
    clock = [start + timedelta(seconds=61)]
    rail = NanoRail(clock=lambda: clock[0])
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.settle(req, H1)
    # Refusing an expired requirement must not consume the block.
    clock[0] = start
    assert rail.settle(req, H1).settled


def test_settle_takes_no_caller_supplied_time():
    """Expiry cannot be bypassed by handing settle an earlier time."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    req_expired = dict(req, expires_at="2000-01-01T00:00:00+00:00")
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(TypeError):
        rail.settle(  # type: ignore[call-arg]
            req_expired, H1, now=datetime(1999, 1, 1, tzinfo=timezone.utc)
        )
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.settle(req_expired, H1)


def test_pay_with_requirement_enforces_expiry_and_match():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    req_expired = dict(req, expires_at="2000-01-01T00:00:00+00:00")
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.pay(DEST, req["amount_raw"], H1, requirement=req_expired)
    with pytest.raises(PaymentNotConfirmed):
        rail.pay(DEST, "1", H1, requirement=req)
    assert rail.pay(DEST, req["amount_raw"], H1, requirement=req).settled


@pytest.mark.parametrize("falsy_expiry", ["", 0, 0.0, False, "   "])
def test_falsy_expires_at_is_not_treated_as_no_expiry(falsy_expiry):
    """Only a missing/``None`` expires_at means "no expiry"; any other falsy
    value is unreadable and refused, never skipped."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="expires_at"):
        rail.settle(dict(req, expires_at=falsy_expiry), H1)
    # The refusal must not consume the block.
    assert rail.settle(req, H1).settled


def test_epoch_expires_at_is_expired():
    """An expires_at at the Unix epoch is long past and must be refused."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.settle(dict(req, expires_at="1970-01-01T00:00:00+00:00"), H1)


@pytest.mark.parametrize(
    "broken",
    [{"rail": "skyfire-usd"}, {"requirement_id": ""}, {"expires_at": "soon"}],
)
def test_malformed_requirement_fails_closed(broken):
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed):
        rail.settle(dict(req, **broken), H1)


def test_rails_sharing_an_outstanding_store_never_share_an_amount(monkeypatch):
    """Two rails (standing in for two workers) that share one store cannot
    issue the same amount for one address."""
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    shared = InMemoryOutstandingAmounts()
    worker_a = NanoRail(outstanding=shared)
    worker_b = NanoRail(outstanding=shared)
    worker_a.requirement("1.00", "/r", DEST)
    with pytest.raises(ValueError):
        worker_b.requirement("1.00", "/r", DEST)


def test_default_rails_in_one_process_never_share_an_amount(monkeypatch):
    """Rails built without ``outstanding`` share the process-wide default, so
    two of them cannot issue the same amount for one address."""
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    NanoRail().requirement("1.00", "/r", DEST)
    with pytest.raises(ValueError):
        NanoRail().requirement("1.00", "/r", DEST)


def test_custom_outstanding_store_is_used():
    """An injected store sees every reservation and every release."""

    class Store:
        def __init__(self):
            self.reserved = []
            self.released = []

        def reserve(self, destination, amount_raw, requirement_id, deadline):
            if self.reserved:  # pretend the first amount is taken elsewhere
                self.reserved.append((destination, amount_raw, requirement_id))
                return True
            self.reserved.append(None)
            return False

        def release(self, destination, amount_raw, requirement_id):
            self.released.append((destination, amount_raw, requirement_id))

        def issued_at(self, destination, amount_raw, requirement_id):
            if (destination, amount_raw, requirement_id) in self.reserved:
                return datetime.now(timezone.utc)
            return None

    store = Store()
    rail = NanoRail(outstanding=store)
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    held = (DEST, req["amount_raw"], req["requirement_id"])
    assert store.reserved == [None, held]
    rail._rpc = ledger((H1, req["amount_raw"]))
    assert rail.settle(req, H1).settled
    assert store.released == [held]


def test_store_refusing_every_amount_yields_no_requirement():
    class Full:
        def reserve(self, *args):
            return False

        def release(self, *args):
            raise AssertionError("nothing was reserved")

    with pytest.raises(ValueError):
        NanoRail(outstanding=Full()).requirement("1.00", "/r", DEST)


def test_rails_sharing_a_claim_store_refuse_a_replay():
    """Two rails (standing in for two workers) that share one claim store
    refuse a block hash the other already settled."""
    shared = InMemoryClaims()
    worker_a = NanoRail(rpc=lambda request: block_info(), claim=shared)
    worker_b = NanoRail(rpc=lambda request: block_info(), claim=shared)
    assert worker_a.verify(H, destination=DEST, amount_raw=AMOUNT).settled
    with pytest.raises(PaymentNotConfirmed, match="already used"):
        worker_b.verify(H.lower(), destination=DEST, amount_raw=AMOUNT)


def test_rails_sharing_stores_settle_a_requirement_once():
    """A requirement issued by one rail and settled there cannot be settled
    again through another rail sharing its stores, even with a fresh block."""
    claims, amounts = InMemoryClaims(), InMemoryOutstandingAmounts()
    worker_a = NanoRail(claim=claims, outstanding=amounts)
    worker_b = NanoRail(claim=claims, outstanding=amounts)
    req = worker_a.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    worker_a._rpc = worker_b._rpc = ledger(
        (H1, req["amount_raw"]), (H2, req["amount_raw"])
    )
    assert worker_a.settle(req, H1).settled
    with pytest.raises(PaymentNotConfirmed):
        worker_b.settle(req, H1)
    with pytest.raises(PaymentNotConfirmed, match="already settled|not issued"):
        worker_b.settle(req, H2)


def test_default_rails_in_one_process_refuse_a_replay():
    """Rails built without ``claim`` share the process-wide default claim
    store, so a block settled on one is refused as a replay on another."""
    a = NanoRail(rpc=lambda request: block_info())
    b = NanoRail(rpc=lambda request: block_info())
    assert a.verify(H, destination=DEST, amount_raw=AMOUNT).settled
    with pytest.raises(PaymentNotConfirmed, match="already used|not issued"):
        b.verify(H, destination=DEST, amount_raw=AMOUNT)


def test_default_rails_settle_a_requirement_once():
    """A requirement settled on one default rail cannot be settled again on
    another default rail in the same process, even with a fresh block."""
    a, b = NanoRail(), NanoRail()
    req = a.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    a._rpc = b._rpc = ledger((H1, req["amount_raw"]), (H2, req["amount_raw"]))
    assert a.settle(req, H1).settled
    with pytest.raises(PaymentNotConfirmed, match="already used|not issued"):
        b.settle(req, H1)
    with pytest.raises(PaymentNotConfirmed, match="already settled|not issued"):
        b.settle(req, H2)


def test_injected_claim_store_is_not_the_default():
    """A rail given its own ``claim`` does not consult the process default."""
    a = NanoRail(rpc=lambda request: block_info())
    b = NanoRail(rpc=lambda request: block_info(), claim=InMemoryClaims())
    assert a.verify(H, destination=DEST, amount_raw=AMOUNT).settled
    assert b.verify(H, destination=DEST, amount_raw=AMOUNT).settled


def timed_ledger(amount, at):
    """An rpc whose only block pays ``amount`` to DEST at unix time ``at``."""
    return lambda request: block_info(amount=amount, at=at)


def test_settle_binds_to_the_issued_requirement_not_the_callers_dict():
    """A returned requirement whose id, address or amount was edited is not
    one this rail issued, so no block can settle it."""
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    other_amount = str(int(req["amount_raw"]) + 1)
    rail._rpc = ledger((H1, req["amount_raw"]), (H2, other_amount))
    forged = [
        dict(req, requirement_id="f" * 32),
        dict(req, nano_address="nano_1someoneelse"),
        dict(req, amount_raw=other_amount),
    ]
    for bad in forged:
        with pytest.raises(PaymentNotConfirmed, match="not issued"):
            rail.settle(bad, H1)
    assert rail.settle(req, H1).settled


def test_late_block_cannot_pay_a_newer_requirement_with_the_same_amount(monkeypatch):
    """Requirement A expires, its amount is handed to B; a block made after A
    expired but before B was issued must not settle B."""
    monkeypatch.setattr(nano.secrets, "randbelow", lambda n: 7)
    rail = NanoRail()
    a = rail.requirement("1.00", "/r", DEST, expires_in_seconds=1)
    time.sleep(1.1)
    b = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    assert b["amount_raw"] == a["amount_raw"]
    now = int(time.time())
    rail._rpc = timed_ledger(b["amount_raw"], now - 120)
    with pytest.raises(PaymentNotConfirmed, match="predates"):
        rail.settle(b, H1)
    rail._rpc = timed_ledger(b["amount_raw"], now)
    assert rail.settle(b, H1).settled


def test_block_made_after_expiry_is_refused():
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)
    rail._rpc = timed_ledger(req["amount_raw"], int(time.time()) + 3600)
    with pytest.raises(PaymentNotConfirmed, match="expired"):
        rail.settle(req, H1)


@pytest.mark.parametrize("stamp", ["", "0", "soon", None])
def test_block_without_a_usable_time_is_refused_by_settle(stamp):
    rail = NanoRail()
    req = rail.requirement("1.00", "/r", DEST, expires_in_seconds=60)

    def rpc(request):
        reply = block_info(amount=req["amount_raw"])
        if stamp is None:
            del reply["local_timestamp"]
        else:
            reply["local_timestamp"] = stamp
        return reply

    rail._rpc = rpc
    with pytest.raises(PaymentNotConfirmed, match="local_timestamp"):
        rail.settle(req, H1)


def test_store_without_issue_records_cannot_settle():
    """A custom store that cannot say when a requirement was issued fails closed."""

    class Bare:
        def reserve(self, *args):
            return True

        def release(self, *args):
            pass

    rail = NanoRail(outstanding=Bare())
    req = rail.requirement("1.00", "/r", DEST)
    rail._rpc = ledger((H1, req["amount_raw"]))
    with pytest.raises(PaymentNotConfirmed, match="not issued"):
        rail.settle(req, H1)
