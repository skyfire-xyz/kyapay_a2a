# KyaPay A2A Payment Protocol Extension

A complete implementation of the KyaPay payment protocol extension for A2A (Agent-to-Agent) using **JWT token-based payments** via the Skyfire API.

## Overview

KyaPay enables AI agents to monetize services through a simple, secure payment flow using JWT tokens instead of blockchain transactions. This library provides all the tools needed to add payment capabilities to your A2A agents.

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

# Wrap your executor with KyaPay support
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

## Testing

```bash
cd python/kyapay_a2a
uv run pytest
uv run pytest --cov=kyapay_a2a --cov-report=term-missing
```

## Examples

See the `python/examples/adk-demo/` directory for a complete working example integrating KyaPay with Google's ADK (Agent Development Kit).

## License

Apache License 2.0 - See LICENSE file for details.
