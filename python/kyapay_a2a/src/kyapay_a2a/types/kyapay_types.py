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
"""Kyapay-specific types for A2A integration."""

from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime


class KyaPayRequirements(BaseModel):
    """Payment requirements for kyapay (replaces PaymentRequirements)."""
    seller_service_id: str  # Skyfire seller service UUID
    token_amount: str       # Decimal USDC amount (e.g., "0.01")
    token_type: Literal["pay", "kya", "kya+pay"] = "pay"
    description: str
    resource: str           # e.g., "/api/generate-image"
    expires_at: Optional[datetime] = None
    identity_permissions: Optional[List[str]] = None  # For kya/kya+pay tokens


class KyaPayToken(BaseModel):
    """Kyapay JWT token (replaces PaymentPayload)."""
    token: str  # JWT token string from Skyfire API
    token_type: Literal["pay", "kya", "kya+pay"]
    buyer_tag: Optional[str] = None  # Optional buyer identifier


class KyaPayVerifyResponse(BaseModel):
    """Token verification response (replaces VerifyResponse)."""
    is_valid: bool
    invalid_reason: Optional[str] = None
    token_data: Optional[dict] = None  # Decoded JWT data if valid


class KyaPayChargeResponse(BaseModel):
    """Token charge response (replaces SettleResponse)."""
    success: bool
    amount_charged: Optional[str] = None
    transaction_id: Optional[str] = None
    error_reason: Optional[str] = None


class KyaPaymentRequiredResponse(BaseModel):
    """Payment required response sent to client."""
    kyapay_version: int = 1  # KyaPay protocol version
    accepts: List[KyaPayRequirements]  # Array of payment options
    error: Optional[str] = None  # Error message if any


# Type alias for token amounts (decimal USDC strings)
TokenAmount = str
