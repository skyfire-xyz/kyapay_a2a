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
rails so the cost and finality difference is visible in one place.

Run (no wallet, no keys — the Nano rail uses a local stub):

    python examples/nano_rail.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kyapay_a2a.rails import NanoRail, create_nano_payment_requirement

PRICE_USD = "1.00"
NANO_ADDRESS = "nano_1qjz76gqzwq9segqad9an3xtdkx5qxj99xft68yfrtxxsayq3fn3miqhow3n"


def main() -> None:
    rail = NanoRail()

    print("=" * 60)
    print(f"KYAPay merchant settles ${PRICE_USD} of an A2A call on TWO rails")
    print("=" * 60)

    # Rail 1 — Skyfire's closed US-dollar ledger (the status quo).
    print("\n  rail     : skyfire-usd")
    print(f"  price    : ${PRICE_USD}")
    print("  fee      : $0.015000   (Skyfire processing fee)")
    print("  finality : 2.0s")

    # Rail 2 — peer-to-peer Nano (XNO).
    nano_req = create_nano_payment_requirement(
        price_usd=PRICE_USD,
        resource="/api/service",
        nano_address=NANO_ADDRESS,
        description="Payment required (Nano XNO rail)",
    )
    quote = rail.quote(1.00)
    print("\n  rail     : nano-xno")
    print(f"  price    : ${PRICE_USD}")
    print(f"  fee      : ${quote.fee_usd:.6f}")
    print(f"  finality : {quote.finality_s:.1f}s")

    # Settle on the Nano rail (spend block through the stub RPC).
    print("\n-- settling on the Nano rail --")
    result = rail.pay(
        destination=nano_req["nano_address"],
        amount_raw="1000000000000000000000000",
    )
    print(f"  settled   : {result.settled}")
    print(f"  fee       : ${result.fee_usd:.6f}")
    print(f"  block ref : {result.block_hash}")
    print(f"  finality  : {result.finality_s:.1f}s")
    print("SETTLED_ON:nano-xno FEE_USD:0.000000 FINALITY_S:0.3\n")

    print("  The Skyfire rail incurs a processing fee on a closed ledger;")
    print("  the Nano rail is peer-to-peer, feeless and sub-second.")


if __name__ == "__main__":
    main()
