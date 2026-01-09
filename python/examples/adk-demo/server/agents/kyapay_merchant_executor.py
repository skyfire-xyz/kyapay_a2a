# Copyright 2025 Google LLC
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
import os
try:
    from typing import override
except ImportError:
    def override(method):
        return method

from a2a.server.agent_execution import AgentExecutor

# Import the executors and types
from kyapay_a2a.executors import KyaPayServerExecutor
from kyapay_a2a.types import (
    KyaPayToken,
    KyaPayRequirements,
    KyaPayChargeResponse,
    KyaPayVerifyResponse,
    KyaPayExtensionConfig,
)
from kyapay_a2a.core.protocol import verify_token, charge_token


class KyaPayMerchantExecutor(KyaPayServerExecutor):
    """
    A concrete implementation of the KyaPayServerExecutor that uses
    Skyfire's kyapay API to verify and charge payment tokens.
    """

    def __init__(
        self,
        delegate: AgentExecutor,
        skyfire_seller_api_key: str = None,
        skyfire_api_host: str = None,
    ):
        super().__init__(delegate, KyaPayExtensionConfig())

        # Seller credentials for charging tokens
        self._skyfire_seller_api_key = skyfire_seller_api_key or os.getenv("SKYFIRE_SELLER_API_KEY")
        self._skyfire_api_host = skyfire_api_host or os.getenv("SKYFIRE_API_HOST", "https://api.skyfire.xyz")

        if not self._skyfire_seller_api_key:
            raise ValueError("SKYFIRE_SELLER_API_KEY is required for KyaPayMerchantExecutor")

    @override
    async def verify_payment(
        self, token: KyaPayToken, requirements: KyaPayRequirements
    ) -> KyaPayVerifyResponse:
        """Verifies the payment token with full JWT validation."""
        print(f"🔍 Verifying payment token for {requirements.description}...")

        response = await verify_token(token, requirements)

        if response.is_valid:
            print("✅ Payment Token Verified!")
        else:
            print(f"⛔ Payment token verification failed: {response.invalid_reason}")

        return response

    @override
    async def charge_payment(
        self, token: KyaPayToken, charge_amount: str
    ) -> KyaPayChargeResponse:
        """Charges the payment token via Skyfire API."""
        print(f"💳 Charging token for amount: {charge_amount} USDC...")

        response = await charge_token(
            token=token,
            charge_amount=charge_amount,
            skyfire_seller_api_key=self._skyfire_seller_api_key,
            skyfire_api_host=self._skyfire_api_host,
        )

        if response.success:
            print(f"✅ Payment Charged! Transaction ID: {response.transaction_id}")
        else:
            print(f"⛔ Payment charge failed: {response.error_reason}")

        return response
