# KYAPay: Identity + Payments for A2A Agents


KYAPay is an **extension** for the [A2A protocol](https://github.com/a2aproject/a2a-python) that adds JWT token-based payments via [Skyfire](https://skyfire.xyz). Merchant agents can monetize their skills; client agents can pay for them automatically.

This implementation brings the [KYAPay protocol](https://www.kyapay.ai/)—an open identity-linked payment standard for agentic AI—to the A2A ecosystem, enabling secure, autonomous transactions between agents.

---

## Overview

```
┌─────────────────┐                           ┌─────────────────┐
│  Client Agent   │  ──── A2A + KYAPay ────▶  │  Merchant Agent │
│  (Buyer)        │  ◀────────────────────    │  (Seller)       │
└─────────────────┘                           └─────────────────┘
        │                                              │
        ▼                                              ▼
   Skyfire API                                   Skyfire API
   (create token)                               (verify & charge)
```

**The Flow:**
1. **Merchant** responds with `payment-required` — here's what I need
2. **Client** creates a signed JWT token via Skyfire and submits it
3. **Merchant** verifies the token, charges it, and delivers the service

No blockchain wallets. No gas fees. Just agents transacting.

---

## Repository Layout

```
.
├── spec/                    # Protocol specification
│   └── v0.1/
│       └── spec.md          # Complete KYAPay extension spec
│
└── python/                  # Python implementation
    ├── kyapay_a2a/          # Core library (pip installable)
    │   ├── src/
    │   └── tests/
    │
    └── examples/
        └── adk-demo/        # Full demo with Gemini ADK
```

---

## Quick Links

| Resource | Description |
|----------|-------------|
| [**🚀 Live Demo**](https://a2a-kyapay-demo.skyfire.xyz) | Try the interactive demo (no setup required) |
| [**🎥 Video Demo**](https://youtu.be/EeG76yh_BQw) | Watch the full payment flow walkthrough |
| [**Specification**](spec/v0.1/spec.md) | Full protocol specification |
| [**Python Library**](python/kyapay_a2a/) | Core library with types, helpers, and executors |
| [**ADK Demo**](python/examples/adk-demo/) | Working example with merchant + client agents |

---


## Readmes

| Resource | Description |
|----------|-------------|
| [**Demo Readme**](python/examples/adk-demo/README.md) | Full end-to-end demo documentation |
| [**Library Readme**](python/kyapay_a2a/README.md) | Core library with types, helpers, and executors |
---

## Usage (Python)

**Note that currently the extension library works with Python versions < 3.14.**

**Install:**
```bash
cd python/kyapay_a2a && uv pip install -e .
```

**Merchant side** — request payment by raising an exception:
```python
from kyapay_a2a import KyaPaymentRequiredException, KyaPayRequirements

raise KyaPaymentRequiredException(
    product_name="Premium Analysis",
    requirements=KyaPayRequirements(
        seller_service_id="your-seller-uuid",
        token_amount="5.00",
        description="Premium Analysis Service"
    )
)
```

**Client side** — create and submit payment token:
```python
from kyapay_a2a import create_token

token = await create_token(
    requirements=payment_required.accepts[0],
    buyer_tag="my-agent",
    skyfire_api_key=os.getenv("SKYFIRE_API_KEY")
)
```

See the [Python library README](python/kyapay_a2a/README.md) for complete documentation.

---

## Architecture

The library follows a **functional core, imperative shell** pattern:

- **Core Protocol** (`kyapay_a2a.core`) — Pure functions for token creation, verification, and charging
- **Executors** (`kyapay_a2a.executors`) — Middleware that wraps your agent and handles the payment flow automatically

Use the core for fine-grained control, or wrap your agent with `KyaPayServerExecutor` for zero-touch payment handling.

---

## Related

- [KYAPay Protocol](https://www.kyapay.ai/) — Open identity-linked payment protocol for agentic AI
- [A2A Protocol](https://github.com/a2aproject/a2a-python) — The agent-to-agent protocol
- [Skyfire](https://skyfire.xyz) — Payment infrastructure for AI agents
- [Video Demo](https://youtu.be/EeG76yh_BQw?si=T0tP-Kn3iJPDWOBK) - Video Demo of A2A Agents Transacting Using The Extension

Please email us if you think there should be a pip package for this extension opensource@skyfire.xyz

---

## License

Apache 2.0
