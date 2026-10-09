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
"""Settle the same A2A call on Skyfire's USD ledger OR the Nano (XNO) rail.

This is the merchant-side view: a KYAPay seller may accept either a Skyfire
JWT token or a peer-to-peer Nano transfer. It shows the *same* $ amount on both
rails so the cost and finality difference is visible in one place. The Nano
settlement is a verification, not a signing step: this example supplies a stub
``rpc`` that confirms a block for the exact raw amount of the requirement.

Run (no wallet, no keys — the Nano rail verifies against a local confirmation
stub that fails closed when no block is found):

    python examples/nano_rail.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kyapay_a2a.rails import NanoRail
from kyapay_a2a.rails.nano import PaymentNotConfirmed

PRICE_USD = "1.00"
# Placeholder XNO/USD rate so the example is deterministic. In production use a
# live quote: the raw amount below is only "$1.00" at this rate.
XNO_USD = "1.0"
NANO_ADDRESS = "nano_1qjz76gqzwq9segqad9an3xtdkx5qxj99xft68yfrtxxsayq3fn3miqhow3n"
# The raw amount the buyer sent; set once the requirement is published (the
# stub below plays a buyer who paid exactly that requirement's amount).
PAID = {"amount_raw": ""}


def _confirming_rpc(request):
    """Local confirmation stub - returns a matching block so the example settles.

    In production, point the rail at a real Nano RPC (e.g. rpc.nano.to) and the
    same ``block_info`` read confirms the buyer's actual block from the ledger.
    """
    if request.get("action") == "block_info":
        # Shape of a real block_info reply for a state send block.
        return {
            "amount": PAID["amount_raw"],
            "confirmed": "true",
            "subtype": "send",
            "contents": {
                "type": "state",
                "link_as_account": NANO_ADDRESS,
            },
        }
    return {"error": "unknown action"}


def main() -> None:
    rail = NanoRail(rpc=_confirming_rpc, xno_usd=XNO_USD)

    print("=" * 60)
    print(f"KYAPay merchant settles ${PRICE_USD} of an A2A call on TWO rails")
    print("=" * 60)

    # Rail 1 — Skyfire's closed US-dollar ledger (the status quo).
    print("\n  rail     : skyfire-usd")
    print(f"  price    : ${PRICE_USD}")
    print("  fee      : $0.015000   (Skyfire processing fee)")
    print("  finality : 2.0s")

    # Rail 2 — peer-to-peer Nano (XNO).
    nano_req = rail.requirement(
        price_usd=PRICE_USD,
        resource="/api/service",
        nano_address=NANO_ADDRESS,
        description="Payment required (Nano XNO rail)",
        expires_in_seconds=300,
    )
    PAID["amount_raw"] = nano_req["amount_raw"]
    quote = rail.quote(1.00)
    print("\n  rail     : nano-xno")
    print(f"  price    : ${PRICE_USD}")
    print(f"  amount   : {nano_req['amount_raw']} raw")
    print(f"  fee      : ${quote.fee_usd:.6f}")
    print(f"  finality : {quote.finality_s:.1f}s")

    # Settle the requirement with the buyer's block: refused once expired or
    # already settled, and only a block for this requirement's amount matches.
    print("\n-- settling on the Nano rail --")
    try:
        result = rail.settle(nano_req, "buyer_block_hash")
        print(f"  settled   : {result.settled}")
        print(f"  fee       : ${result.fee_usd:.6f}")
        print(f"  block ref : {result.block_hash}")
        print(f"  finality  : {result.finality_s:.1f}s")
        print("SETTLED_ON:nano-xno FEE_USD:0.000000 FINALITY_S:0.3\n")
    except PaymentNotConfirmed as exc:
        print(f"  NOT settled - failed closed: {exc}")

    print("  The Skyfire rail incurs a processing fee on a closed ledger;")
    print("  the Nano rail is peer-to-peer, feeless and sub-second.")


if __name__ == "__main__":
    main()
