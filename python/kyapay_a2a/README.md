# KYAPay A2A Payment Protocol Extension

A complete implementation of the KYAPay payment protocol extension for A2A (Agent-to-Agent) using **JWT token-based payments** via the Skyfire API.

This library implements [KYAPay](https://www.kyapay.ai/), an open identity-linked payment protocol for agentic AI, providing a production-ready integration for the A2A protocol ecosystem.

## Overview

KYAPay enables AI agents to monetize services through a simple, secure payment flow using JWT tokens instead of blockchain transactions. This library provides all the tools needed to add payment capabilities to your A2A agents.

**Learn More:** For detailed information about the KYAPay protocol, including its vision for identity-linked agentic transactions, token structure, and integration with other agent protocols (MCP, ACP), visit [www.kyapay.ai](https://www.kyapay.ai/).

## Key Features

- **JWT Token-Based**: Uses Skyfire API to create and verify payment tokens (no blockchain wallets needed)
- **Exception-Based Payment Flow**: Raise `KyaPaymentRequiredException` to request payment dynamically
- **Helper Functions**: High-level decorators and utilities for easy integration
- **Server Executor**: Automatic payment handling with the `KyaPayServerExecutor` wrapper
- **Type-Safe**: Full Pydantic models for all payment data structures

## Installation

**Note that currently the extension library works with Python versions < 3.14.**

```bash
cd python/kyapay_a2a
uv pip install -e .
```

## Quick Start

### Server Side (Merchant Agent)

```python
from kyapay_a2a import (
    KyaPaymentRequiredException,
    KyaPayServerExecutor,
    KyaPayExtensionConfig,
)
from a2a.server import AgentExecutor

# Your agent logic
class MyMerchantAgent:
    def process_request(self, request):
        # Raise exception to request payment
        raise KyaPaymentRequiredException(
            product_name="Premium AI Service",
            requirements=KyaPayRequirements(
                seller_service_id="your-seller-uuid",
                token_amount="5.00",  # USDC amount
                token_type="pay",
                description="Premium AI Service",
                resource="/api/premium-service"
            )
        )

# Wrap your executor with KYAPay support
executor = KyaPayServerExecutor(
    delegate=your_base_executor,
    config=KyaPayExtensionConfig()
)
```

The server executor will:
1. Catch `KyaPaymentRequiredException` and send payment requirements to client
2. Receive payment token from client
3. Verify token via Skyfire JWKS
4. Charge token via Skyfire API
5. Execute your agent logic after successful payment

### Client Side (Buyer Agent)

```python
from kyapay_a2a import create_token, KyaPayUtils

# When you receive a payment-required response:
utils = KyaPayUtils()
payment_required = utils.get_payment_requirements(task)

# Create payment token via Skyfire API
token = await create_token(
    requirements=payment_required.accepts[0],
    buyer_tag="your-buyer-tag",
    skyfire_api_key="your-api-key",
    skyfire_api_host="https://api.skyfire.xyz"
)

# Submit token back to merchant
submission = create_payment_submission_message(task.id, token)
```

## Core Types

### KyaPayRequirements
Payment requirements sent from merchant to client:
```python
class KyaPayRequirements(BaseModel):
    seller_service_id: str  # Skyfire seller service UUID
    token_amount: str       # Decimal USDC amount (e.g., "0.01")
    token_type: Literal["pay", "kya", "kya+pay"] = "pay"
    description: str
    resource: str           # e.g., "/api/generate-image"
    expires_at: Optional[datetime] = None
    identity_permissions: Optional[List[str]] = None
```

### KyaPayToken
JWT token created by client via Skyfire API:
```python
class KyaPayToken(BaseModel):
    token: str  # JWT token string
    token_type: Literal["pay", "kya", "kya+pay"]
    buyer_tag: Optional[str] = None
```

### KyaPaymentRequiredResponse
Response sent to client when payment is required:
```python
class KyaPaymentRequiredResponse(BaseModel):
    kyapay_version: int = 1
    accepts: List[KyaPayRequirements]
    error: Optional[str] = None
```

### KyaPayVerifyResponse
Token verification result:
```python
class KyaPayVerifyResponse(BaseModel):
    is_valid: bool
    invalid_reason: Optional[str] = None
    token_data: Optional[dict] = None
```

### KyaPayChargeResponse
Token charge result:
```python
class KyaPayChargeResponse(BaseModel):
    success: bool
    amount_charged: Optional[str] = None
    transaction_id: Optional[str] = None
    error_reason: Optional[str] = None
```

## Metadata Keys

The protocol uses these metadata keys in A2A messages:

```python
class KyaPayMetadata:
    STATUS_KEY = "kyapay.payment.status"
    REQUIRED_KEY = "kyapay.payment.required"    # Contains KyaPaymentRequiredResponse
    PAYLOAD_KEY = "kyapay.payment.payload"      # Contains KyaPayToken
    RECEIPTS_KEY = "kyapay.payment.receipts"    # Contains array of KyaPayChargeResponse
    ERROR_KEY = "kyapay.payment.error"          # Error code (when failed)
```

## Payment States

```python
class PaymentStatus(str, Enum):
    PAYMENT_REQUIRED = "payment-required"      # Payment requested
    PAYMENT_SUBMITTED = "payment-submitted"    # Token submitted by client
    PAYMENT_VERIFIED = "payment-verified"      # Token verified (JWKS check passed)
    PAYMENT_REJECTED = "payment-rejected"      # Client rejected payment
    PAYMENT_COMPLETED = "payment-completed"    # Payment charged successfully
    PAYMENT_FAILED = "payment-failed"          # Payment failed
```

## Core Functions

### Merchant Functions

```python
from kyapay_a2a import create_payment_requirements

# Create payment requirements
requirements = create_payment_requirements(
    price="5.00",
    seller_service_id="your-uuid",
    description="AI Service",
    resource="/api/service"
)
```

### Protocol Functions

```python
from kyapay_a2a import create_token, verify_token, charge_token

# Buyer: Create payment token
token = await create_token(
    requirements=requirements,
    buyer_tag="buyer-123",
    skyfire_api_key="key",
    skyfire_api_host="https://api.skyfire.xyz"
)

# Seller: Verify token (JWKS signature verification)
verify_response = await verify_token(token, requirements)

# Seller: Charge token via Skyfire API
charge_response = await charge_token(
    token=token,
    charge_amount="5.00",
    skyfire_seller_api_key="seller-key",
    skyfire_api_host="https://api.skyfire.xyz"
)
```

### Helper Functions

```python
from kyapay_a2a import require_payment, paid_service

# Simple payment requirement
def my_service():
    require_payment(
        price="5.00",
        seller_service_id="uuid",
        resource="/api/service"
    )
    # Service logic here

# Decorator approach
@paid_service(price="10.00", seller_service_id="uuid")
def premium_service():
    return "Premium content"
```

### Utility Functions

```python
from kyapay_a2a import KyaPayUtils

utils = KyaPayUtils()

# Extract payment requirements from task
requirements = utils.get_payment_requirements(task)

# Extract payment token from message
token = utils.get_payment_token(message)

# Get payment status
status = utils.get_payment_status(task)

# Create payment-required task
task = utils.create_payment_required_task(task, payment_required_response)

# Record payment success/failure
task = utils.record_payment_success(task, charge_response)
task = utils.record_payment_failure(task, error_code, charge_response)
```

## Extension Declaration

```python
from kyapay_a2a import KYAPAY_EXTENSION_URI, get_extension_declaration

# Add to your AgentCard
extension = get_extension_declaration(
    description="Supports kyapay payments",
    required=True
)

# In your AgentCard:
{
    "capabilities": {
        "extensions": [extension]
    }
}
```

## Error Handling

```python
from kyapay_a2a import (
    KyaPayError,
    KyaPayErrorCode,
    KyaPaymentRequiredException,
    ValidationError,
    PaymentError
)

class KyaPayErrorCode:
    INVALID_TOKEN = "INVALID_TOKEN"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
```

## Complete Payment Flow

### 1. Merchant Sends Payment Required

```python
# Task state: input-required
# Task metadata:
{
    "kyapay.payment.status": "payment-required",
    "kyapay.payment.required": {
        "kyapay_version": 1,
        "accepts": [{
            "seller_service_id": "uuid",
            "token_amount": "5.00",
            "token_type": "pay",
            "description": "AI Service",
            "resource": "/api/service"
        }]
    }
}
```

### 2. Client Creates and Submits Token

```python
# Message metadata:
{
    "kyapay.payment.status": "payment-submitted",
    "kyapay.payment.payload": {
        "token": "eyJhbGc...",  # JWT token
        "token_type": "pay",
        "buyer_tag": "buyer-123"
    }
}
```

### 3. Merchant Verifies and Charges

The `KyaPayServerExecutor` automatically:
1. Verifies JWT signature using Skyfire JWKS
2. Charges token via Skyfire API
3. Records result in task metadata

```python
# Task metadata after payment:
{
    "kyapay.payment.status": "payment-completed",
    "kyapay.payment.receipts": [{
        "success": true,
        "amount_charged": "5.00",
        "transaction_id": "txn_123"
    }]
}
```

## Nano (XNO) settlement rail

Skyfire's KYAPay settles on a closed US-dollar ledger by default. This repository
also ships an optional **peer-to-peer Nano (XNO) rail** so a merchant can offer a
feeless, sub-second, self-custodial alternative in addition to a Skyfire token.
Adding it is additive and non-breaking — the default flow is unchanged.

```python
from kyapay_a2a.rails import NanoRail

# One rail, one XNO/USD rate (1.0 here is a placeholder: use a live quote).
rail = NanoRail(rpc=my_rpc, xno_usd="1.0")

# Merchant publishes a Nano payment requirement (parallel to a Skyfire token).
# The requirement binds the advertised USD price to an exact raw amount,
# converted with the rail's own rate plus a small random tag (under 10^6 raw)
# that makes the amount unique to this requirement.
requirement = rail.requirement(
    price_usd="1.00",
    resource="/api/service",
    nano_address="nano_1qjz76gqzwq9segqad9an3xtdkx5qxj99xft68yfrtxxsayq3fn3miqhow3n",
    expires_in_seconds=300,
)

quote = rail.quote(1.00)                    # fee $0.00, finality 0.3s
# The buyer sends exactly requirement["amount_raw"] and hands back the hash.
result = rail.settle(requirement, "buyer_block_hash")
print(result.settled, result.block_hash)    # True <block hash>
```

Settlement is a **merchant-side verification, not a signer**: the buyer signs
and broadcasts the send block; a merchant asks its `rpc` for that block's
`block_info` and only reports `settled=True` when the node marks the block
`confirmed`, it is a send, its recipient and top-level `amount` match the
advertised requirement exactly, and the block hash has not been used before
(one block pays for one delivery; pass `claim=` to back that check with shared
storage in a multi-process merchant). `settle` also refuses an expired
requirement and settles each requirement once; because each requirement's
amount is unique, a block someone paid for another requirement does not match.
Prices that are zero, negative or below one raw are rejected when the
requirement is built. The requirement is a plain dict offered next to a
`KyaPayRequirements`, not one: that model needs a Skyfire `seller_service_id`. This **fails closed** — an unconfigured
rail or an unmatched block is never reported as paid. Quote (`fee_usd=0`,
`finality_s=0.3`) and the confirmation read go through a pluggable `rpc` seam,
so the example and tests run with **no wallet and no keys** — the shipped stub
confirms nothing, and the example supplies a stub that confirms only the exact
amount. To go live, point `rpc` at a real Nano RPC (e.g. `rpc.nano.to`) or wrap
an existing Nano x402 client (e.g. `x402nano-exact` / `feeless402`), which this
rail reuses rather than rebuilding.

Run the two-rail comparison:

```bash
cd python/kyapay_a2a
python examples/nano_rail.py
```

## Testing

```bash
cd python/kyapay_a2a
uv run pytest
uv run pytest --cov=kyapay_a2a --cov-report=term-missing
```

## Examples

See the `python/examples/adk-demo/` directory for a complete working example integrating KYAPay with Gemini ADK (Agent Development Kit).

## License

Apache License 2.0 - See LICENSE file for details.
