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
"""Merchant-side payment requirement creation for kyapay."""

from typing import Optional, List, Literal
from datetime import datetime, timedelta

from ..types import KyaPayRequirements


def create_payment_requirements(
    price: str,
    seller_service_id: str,
    resource: str,
    description: str = "Payment required for this service",
    token_type: Literal["pay", "kya", "kya+pay"] = "pay",
    expires_in_seconds: Optional[int] = None,
    identity_permissions: Optional[List[str]] = None,
) -> KyaPayRequirements:
    """Create kyapay payment requirements.

    Args:
        price: Token amount as decimal string (e.g., "0.01")
        seller_service_id: Skyfire seller service UUID
        resource: Resource identifier (e.g., "/api/service")
        description: Human-readable description
        token_type: Type of token to create (pay, kya, kya+pay)
        expires_in_seconds: Optional expiration time
        identity_permissions: Required for kya/kya+pay tokens

    Returns:
        KyaPayRequirements with payment details
    """
    expires_at = None
    if expires_in_seconds:
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in_seconds)

    return KyaPayRequirements(
        seller_service_id=seller_service_id,
        token_amount=price,
        token_type=token_type,
        description=description,
        resource=resource,
        expires_at=expires_at,
        identity_permissions=identity_permissions,
    )
