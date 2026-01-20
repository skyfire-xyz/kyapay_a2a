# A2A Protocol: KyaPay Payments Extension v0.1

## 1. Abstract

The KyaPay Payments Extension is an **Extension** for the Agent-to-Agent (A2A) protocol. It enables agents to monetize services through JWT token-based payments via the Skyfire payment infrastructure, reviving the spirit of the HTTP 402 "Payment Required" status code for the world of AI agents.

This specification defines the required data structures and state machine for JWT-based payments between a Client Agent (buyer) and a Merchant Agent (seller).

## 2. Extension URI

The canonical URI for this version of the extension is:

```
https://github.com/skyfire-xyz/a2a-kyapay/tree/main/v0.1
```

Implementations of this extension MUST use this URI for declaration and activation.

## 3. Extension Declaration

Agents that support this extension MUST declare it in the `extensions` array of their `AgentCard`.

```json
{
  "capabilities": {
    "extensions": [
      {
        "uri": "https://github.com/skyfire-xyz/a2a-kyapay/tree/main/v0.1",
        "description": "Supports payments using the KyaPay protocol via Skyfire API.",
        "required": true
      }
    ]
  }
}
```

### 3.1. Required Extension

Setting `required: true` is recommended. This signals to clients that they **MUST** understand and implement the KyaPay protocol to interact with the agent's monetized skills. If a required extension is not activated by the client, the agent SHOULD reject the request.

## 4. Extension Activation

Clients MUST request activation of this extension by including its URI in the `X-A2A-Extensions` HTTP header:

```
X-A2A-Extensions: https://github.com/skyfire-xyz/a2a-kyapay/tree/main/v0.1
```

Servers MAY echo this header in responses to confirm activation.

## 5. Payment Protocol Flow

The KyaPay extension represents the payment lifecycle using the high-level A2A Task state (e.g., `input-required`, `completed`) and a granular `kyapay.payment.status` field. The flow involves a Client Agent (acting on behalf of a user/buyer) and a Merchant Agent (selling a service).

### 5.1. Roles & Responsibilities

#### Client Agent

The Client Agent acts on behalf of a user, orchestrating the payment flow.

- Initiates service requests to the Merchant Agent
- Receives a `Task` with `state: input-required` and extracts the `KyaPaymentRequiredResponse` from `task.status.message.metadata`
- Evaluates the payment requirements (price, token type, etc.)
  - If accepting: creates a signed `KyaPayToken` via the Skyfire API and submits it
  - If rejecting: responds with `kyapay.payment.status: payment-rejected`
- Waits for and processes the final `Task` with payment receipt

#### Merchant Agent

The Merchant Agent provides a monetized skill or service.

- Determines when a service request requires payment
- Responds with an `input-required` Task containing `KyaPaymentRequiredResponse` in the message metadata
- Receives the payment submission and verifies the token via Skyfire JWKS
- Charges the token via Skyfire API
- Returns a final Task with `kyapay.payment.receipts` containing the transaction result

### 5.2. Sequence Diagram

```
┌──────────────┐                              ┌────────────────┐
│ Client Agent │                              │ Merchant Agent │
└──────┬───────┘                              └───────┬────────┘
       │                                              │
       │  1. Request service (Message)                │
       │─────────────────────────────────────────────>│
       │                                              │
       │  2. Task (state: input-required)             │
       │     metadata: kyapay.payment.required        │
       │<─────────────────────────────────────────────│
       │                                              │
       │  3. Create KyaPayToken via Skyfire API       │
       │                                              │
       │  4. Message (taskId, kyapay.payment.payload) │
       │─────────────────────────────────────────────>│
       │                                              │
       │                    5. Verify token (JWKS)    │
       │                    6. Charge token (API)     │
       │                                              │
       │  7. Task (state: completed/failed)           │
       │     metadata: kyapay.payment.receipts        │
       │<─────────────────────────────────────────────│
       │                                              │
```

### 5.3. Step 1: Payment Request (Merchant → Client)

When payment is required, the Merchant Agent creates a `Task` with:
- `status.state`: `"input-required"`
- `status.message.metadata`: Contains `kyapay.payment.status` and `kyapay.payment.required`

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "kind": "task",
    "id": "task-123",
    "contextId": "ctx-456",
    "status": {
      "state": "input-required",
      "message": {
        "kind": "message",
        "role": "agent",
        "parts": [{ "kind": "text", "text": "Payment is required for this service." }],
        "metadata": {
          "kyapay.payment.status": "payment-required",
          "kyapay.payment.required": {
            "kyapay_version": 1,
            "accepts": [
              {
                "seller_service_id": "uuid-of-seller-service",
                "token_amount": "5.00",
                "token_type": "pay",
                "description": "Premium AI Analysis",
                "resource": "/api/analyze"
              }
            ]
          }
        }
      }
    }
  }
}
```

### 5.4. Step 2: Payment Authorization (Client)

The Client Agent extracts the `KyaPaymentRequiredResponse` and decides whether to proceed:

1. **Accept**: Create a `KyaPayToken` by calling the Skyfire API with the selected `KyaPayRequirements`
2. **Reject**: Send a message with `kyapay.payment.status: payment-rejected`

### 5.5. Step 3: Payment Submission (Client → Merchant)

The Client Agent sends a `Message` linked to the original Task via `taskId`:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "req-002",
  "params": {
    "message": {
      "taskId": "task-123",
      "role": "user",
      "parts": [{ "kind": "text", "text": "Here is my payment." }],
      "metadata": {
        "kyapay.payment.status": "payment-submitted",
        "kyapay.payment.payload": {
          "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
          "token_type": "pay",
          "buyer_tag": "buyer-agent-123"
        }
      }
    }
  }
}
```

### 5.6. Step 4: Verification and Settlement (Merchant)

The Merchant Agent:

1. **Verifies** the JWT token using Skyfire's JWKS endpoint
2. **Charges** the token via Skyfire API
3. **Updates** the Task with the result

### 5.7. Step 5: Payment Complete (Merchant → Client)

On success, the Merchant returns a completed Task:

```json
{
  "jsonrpc": "2.0",
  "id": "req-003",
  "result": {
    "kind": "task",
    "id": "task-123",
    "contextId": "ctx-456",
    "status": {
      "state": "completed",
      "message": { 
        "kind": "message",
        "role": "agent",
        "parts": [{ "kind": "text", "text": "Payment successful. Here is your result." }],
        "metadata": {
          "kyapay.payment.status": "payment-completed",
          "kyapay.payment.receipts": [
            {
            "success": true,
              "amount_charged": "5.00",
              "transaction_id": "txn_abc123"
            }
          ]
        }
      }
    },
    "artifacts": [
      {
        "artifactId": "result-001",
        "parts": [{ "kind": "text", "text": "Analysis complete..." }]
      }
    ]
  }
}
```

## 6. Data Structures

### 6.1. KyaPayRequirements

Payment requirements sent from merchant to client. The `accepts` array allows merchants to offer multiple payment options.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `seller_service_id` | string | Yes | Skyfire seller service UUID |
| `token_amount` | string | Yes | Decimal USDC amount (e.g., "5.00") |
| `token_type` | enum | No | One of: `"pay"`, `"kya"`, `"kya+pay"`. Default: `"pay"` |
| `description` | string | Yes | Human-readable description of the service |
| `resource` | string | Yes | Resource identifier (e.g., "/api/analyze") |
| `expires_at` | datetime | No | Optional expiration timestamp |
| `identity_permissions` | string[] | No | Required for `kya` or `kya+pay` tokens |

### 6.2. KyaPayToken

JWT token created by the client via the Skyfire API.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | JWT token string from Skyfire API |
| `token_type` | enum | Yes | One of: `"pay"`, `"kya"`, `"kya+pay"` |
| `buyer_tag` | string | No | Optional buyer identifier |

### 6.3. KyaPaymentRequiredResponse

Wrapper object sent in task metadata when payment is required.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `kyapay_version` | int | Yes | Protocol version (currently `1`) |
| `accepts` | KyaPayRequirements[] | Yes | Array of accepted payment options |
| `error` | string | No | Error message if applicable |

### 6.4. KyaPayChargeResponse

Transaction result returned after payment settlement.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `success` | bool | Yes | Whether the charge succeeded |
| `amount_charged` | string | No | Amount charged (if successful) |
| `transaction_id` | string | No | Skyfire transaction ID (if successful) |
| `error_reason` | string | No | Error description (if failed) |

## 7. Metadata Keys

The protocol uses these metadata keys in A2A `Message` objects:

| Key | Description |
|-----|-------------|
| `kyapay.payment.status` | **(Required)** Current payment state |
| `kyapay.payment.required` | `KyaPaymentRequiredResponse` object (in payment-required messages) |
| `kyapay.payment.payload` | `KyaPayToken` object (in payment-submitted messages) |
| `kyapay.payment.receipts` | Array of `KyaPayChargeResponse` objects (in final messages) |
| `kyapay.payment.error` | Error code string (when status is payment-failed) |

## 8. Payment States

The `kyapay.payment.status` field tracks the payment lifecycle:

| Status | Description | Next States |
|--------|-------------|-------------|
| `payment-required` | Payment requirements sent to client | `payment-submitted`, `payment-rejected` |
| `payment-submitted` | Client has submitted payment token | `payment-verified`, `payment-failed` |
| `payment-verified` | Token signature verified via JWKS | `payment-completed`, `payment-failed` |
| `payment-rejected` | Client rejected the payment requirements | (terminal) |
| `payment-completed` | Payment charged successfully | (terminal) |
| `payment-failed` | Payment processing failed | (terminal) |

### 8.1. State Diagram

```
                    ┌─────────────────┐
                    │ payment-required│
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
    ┌──────────────────┐          ┌──────────────────┐
    │ payment-submitted│          │ payment-rejected │
    └────────┬─────────┘          └──────────────────┘
             │
             ▼
    ┌──────────────────┐
    │ payment-verified │
    └────────┬─────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────────┐  ┌──────────────┐
│  completed   │  │    failed    │
└──────────────┘  └──────────────┘
```

## 9. Error Handling

When payment fails, the Merchant Agent MUST:
1. Set `kyapay.payment.status` to `"payment-failed"`
2. Include the error code in `kyapay.payment.error`
3. Provide details in `kyapay.payment.receipts`

### 9.1. Error Codes

| Code | Description |
|------|-------------|
| `INSUFFICIENT_FUNDS` | The buyer's account has insufficient funds |
| `INVALID_TOKEN` | The JWT token is malformed or has an invalid signature |
| `EXPIRED_TOKEN` | The token has expired |
| `SERVICE_MISMATCH` | The token's service ID doesn't match the requirements |
| `INVALID_AMOUNT` | The token amount doesn't match requirements |
| `CHARGE_FAILED` | The Skyfire API charge request failed |
| `TOKEN_CREATION_FAILED` | Failed to create token via Skyfire API |

### 9.2. Example Error Response

```json
{
  "kind": "task",
  "id": "task-123",
  "contextId": "ctx-456",
  "status": {
    "state": "failed",
    "message": {
      "kind": "message",
      "role": "agent",
      "parts": [{ "kind": "text", "text": "Payment failed: Invalid token signature." }],
      "metadata": {
        "kyapay.payment.status": "payment-failed",
        "kyapay.payment.error": "INVALID_TOKEN",
        "kyapay.payment.receipts": [
          {
            "success": false,
            "error_reason": "JWT signature verification failed"
          }
        ]
      }
    }
  }
}
```

## 10. Security Considerations

- **Token Security**: JWT tokens contain payment authorization and MUST be transmitted over HTTPS
- **Signature Verification**: Merchant Agents MUST verify JWT signatures using Skyfire's JWKS endpoint before charging
- **Token Expiration**: Clients SHOULD set reasonable expiration times; merchants MUST reject expired tokens
- **Idempotency**: The `transaction_id` in charge responses enables idempotent retry handling
- **Transport Security**: All A2A communication MUST use HTTPS/TLS

## 11. References

- [A2A Protocol Specification](https://github.com/a2aproject/a2a-python)
- [A2A Extensions Documentation](https://github.com/a2aproject/A2A/blob/main/docs/topics/extensions.md)
- [Skyfire API Documentation](https://docs.skyfire.xyz)
