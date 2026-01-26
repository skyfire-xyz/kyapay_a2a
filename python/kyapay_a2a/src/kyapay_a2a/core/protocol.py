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
"""Core protocol operations for kyapay payment verification and charging."""

import httpx
import requests
import validators
from jose import jwt
from jose.exceptions import JWTError
from decimal import Decimal, InvalidOperation
import uuid
import time
import os
from typing import Optional
import logging

from ..types import (
    KyaPayRequirements,
    KyaPayToken,
    KyaPayVerifyResponse,
    KyaPayChargeResponse,
)

logger = logging.getLogger(__name__)

# Skyfire JWT verification constants
JWKS_URL = "https://app.skyfire.xyz/.well-known/jwks.json"
JWT_ISSUER = "https://app.skyfire.xyz"
ALGORITHMS = ["ES256"]


# ============================================================================
# Helper functions for JWT validation
# ============================================================================

def _get_jwks(jwks_url: str = JWKS_URL):
    """Fetch JWKS from Skyfire."""
    response = requests.get(jwks_url)
    response.raise_for_status()
    return response.json()


def _to_int(v):
    """Safely convert to int."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_decimal(v):
    """Safely convert to Decimal."""
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_valid_uuid(val):
    """Check if value is valid UUID."""
    try:
        uuid.UUID(str(val))
        return True
    except Exception:
        return False


# ============================================================================
# BUYER SIDE - Token Creation
# ============================================================================

async def create_token(
    requirements: KyaPayRequirements,
    buyer_tag: str,
    skyfire_api_key: Optional[str] = None,
    skyfire_api_host: Optional[str] = None,
) -> KyaPayToken:
    """Create a kyapay token (buyer side).

    Args:
        requirements: Payment requirements from merchant
        buyer_tag: Buyer identifier (configurable per-request)
        skyfire_api_key: Buyer's API key (defaults to SKYFIRE_API_KEY env)
        skyfire_api_host: API host (defaults to SKYFIRE_API_HOST env)

    Returns:
        KyaPayToken with JWT token string
    """
    api_key = skyfire_api_key or os.getenv("SKYFIRE_API_KEY")
    api_host = skyfire_api_host or os.getenv("SKYFIRE_API_HOST")

    if not api_key or not api_host:
        raise ValueError("SKYFIRE_API_KEY and SKYFIRE_API_HOST required")

    url = f"{api_host}/api/v1/tokens"
    headers = {
        "skyfire-api-key": api_key,
        "content-type": "application/json",
    }

    payload = {
        "type": requirements.token_type,
        "buyerTag": buyer_tag,
        "tokenAmount": requirements.token_amount,
        "sellerServiceId": requirements.seller_service_id,
    }

    if requirements.expires_at:
        payload["expiresAt"] = requirements.expires_at.isoformat()
    if requirements.identity_permissions:
        payload["identityPermissions"] = requirements.identity_permissions


    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30.0)
        response.raise_for_status()

        data = response.json()
        logger.info("✅ Token created successfully")

        return KyaPayToken(
            token=data["token"],
            token_type=requirements.token_type,
            buyer_tag=buyer_tag,
        )


# ============================================================================
# SELLER SIDE - Token Verification & Charging
# ============================================================================

async def verify_token(
    token: KyaPayToken,
    requirements: KyaPayRequirements,
    audience: Optional[str] = None,
) -> KyaPayVerifyResponse:
    """Verify kyapay token with full JWT validation.

    Takes:
    Token: The kyapay token to verify
    Requirements: The payment requirements
    Audience: The audience seller service id to verify the token against

    Performs:
    - JWKS signature verification
    - Token type validation (must be pay+JWT, kya+JWT, or kya+pay+JWT)
    - Issuer/audience validation
    - Expiration validation
    - Amount/price validation against requirements
    - UUID validation for jti/sub
    - Email validation for buyer identity
    - ensure the ENV is production
    """
    if not token.token:
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason="Missing token"
        )

    # Fetch JWKS for signature verification
    try:
        jwks = _get_jwks(JWKS_URL)
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason=f"JWKS fetch failed: {str(e)}"
        )

    # Decode and verify JWT
    try:

        if audience:
            payload = jwt.decode(
                token.token,
                jwks,
                algorithms=ALGORITHMS,
                issuer=JWT_ISSUER,
                audience=audience,
            )
        else:
            payload = jwt.decode(
                token.token,
                jwks,
                algorithms=ALGORITHMS,
                issuer=JWT_ISSUER,
                options={"verify_aud": False},
            )

        # Verify token type header
        protected_header = jwt.get_unverified_header(token.token)
        typ = protected_header.get("typ")

        # Accept different token types based on requirements
        expected_typ_map = {
            "pay": "pay+JWT",
            "kya": "kya+JWT",
            "kya+pay": "kya+pay+JWT",
        }
        expected_typ = expected_typ_map.get(requirements.token_type)

        if typ != expected_typ:
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason=f"Invalid token type: expected {expected_typ}, got {typ}"
            )

    except JWTError as err:
        logger.error(f"JWT verification failed: {err}")
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason=f"JWT verification failed: {str(err)}"
        )

    # Validate environment (production only)
    if payload.get("env") != "production":
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason=f"Invalid environment: {payload.get('env')}"
        )

    # Validate timestamps
    now = int(time.time())

    iat = payload.get("iat")
    if not isinstance(iat, int) or iat > now:
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason="Issued-at time is invalid or in the future"
        )

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= now:
        return KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason="Token has expired"
        )

    # Validate UUIDs (jti, sub)
    for field in ["jti", "sub"]:
        if not _is_valid_uuid(payload.get(field)):
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason=f"Invalid {field}: not a valid UUID"
            )

    # Validate payment fields (for pay and kya+pay tokens)
    if requirements.token_type in ["pay", "kya+pay"]:
        value = _to_int(payload.get("value"))
        if value is None or value <= 0:
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason="Token value must be a positive integer"
            )

        amount = _to_decimal(payload.get("amount"))
        if amount is None or amount <= 0:
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason="Token amount must be a positive number"
            )

        # Validate currency is USD
        cur = payload.get("cur")
        if cur != "USD":
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason=f"Invalid currency: expected USD, got {cur}"
            )

        # Validate amount matches requirements
        required_amount = _to_decimal(requirements.token_amount)
        if amount < required_amount:
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason=f"Insufficient token amount: got {amount}, required {required_amount}"
            )

    # Validate identity fields (for kya and kya+pay tokens)
    if requirements.token_type in ["kya", "kya+pay"]:
        bid = payload.get("bid", {})
        skyfire_email = bid.get("skyfireEmail")

        if not validators.email(skyfire_email):
            return KyaPayVerifyResponse(
                is_valid=False,
                invalid_reason="Invalid buyer email format"
            )

    # All validations passed
    logger.info("✅ Token verified successfully")
    return KyaPayVerifyResponse(
        is_valid=True,
        token_data=payload,
    )


async def charge_token(
    token: KyaPayToken,
    charge_amount: str,
    skyfire_seller_api_key: Optional[str] = None,
    skyfire_api_host: Optional[str] = None,
) -> KyaPayChargeResponse:
    """Charge a kyapay token (seller side).

    Args:
        token: The kyapay token to charge
        charge_amount: Amount to charge as decimal string (e.g., "0.01")
        skyfire_seller_api_key: Seller's API key (defaults to SKYFIRE_SELLER_API_KEY env)
        skyfire_api_host: API host (defaults to SKYFIRE_API_HOST env)

    Returns:
        KyaPayChargeResponse with charge result
    """
    api_key = skyfire_seller_api_key or os.getenv("SKYFIRE_SELLER_API_KEY")
    api_host = skyfire_api_host or os.getenv("SKYFIRE_API_HOST")

    if not api_key or not api_host:
        raise ValueError("SKYFIRE_SELLER_API_KEY and SKYFIRE_API_HOST required")

    url = f"{api_host}/api/v1/tokens/charge"
    headers = {
        "skyfire-api-key": api_key,
        "content-type": "application/json",
    }

    payload = {
        "token": token.token,
        "chargeAmount": charge_amount,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30.0)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Token charged successfully: {data}")

                return KyaPayChargeResponse(
                    success=True,
                    amount_charged=data.get("amountCharged"),
                    transaction_id=data.get("transactionId"),
                )
            else:
                error_msg = f"Token charge failed: {response.status_code} - {response.text}"
                logger.error(f"⛔ {error_msg}")

                return KyaPayChargeResponse(
                    success=False,
                    error_reason=error_msg,
                )

    except Exception as e:
        error_msg = f"Token charge failed: {str(e)}"
        logger.error(f"⛔ {error_msg}", exc_info=True)

        return KyaPayChargeResponse(
            success=False,
            error_reason=error_msg,
        )
