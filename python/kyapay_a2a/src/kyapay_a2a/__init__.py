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
"""kyapay_a2a - KyaPay Payment Protocol Extension for A2A."""

# A2A Extension Types & Functions
from .types import (
    # Extension Constants
    KYAPAY_EXTENSION_URI,
    # KyaPay Types
    KyaPayRequirements,
    KyaPayToken,
    KyaPayVerifyResponse,
    KyaPayChargeResponse,
    # A2A-Specific Types
    PaymentStatus,
    # Configuration
    KyaPayExtensionConfig,
    # Error Types
    KyaPayError,
    MessageError,
    ValidationError,
    PaymentError,
    StateError,
    KyaPaymentRequiredException,
    KyaPayErrorCode,
    # Extension utilities
    get_extension_declaration,
    check_extension_activation,
    add_extension_activation_header,
)

# Core Functions
from .core import (
    # Merchant functions
    create_payment_requirements,
    # Protocol functions (buyer + seller)
    create_token,
    verify_token,
    charge_token,
    # State Management
    KyaPayUtils,
    create_payment_submission_message,
    extract_task_id,
    # Helper functions
    require_payment,
    require_payment_choice,
    paid_service,
    smart_paid_service,
    create_tiered_payment_options,
    check_payment_context,
    # Agent utilities
    create_kyapay_agent_card,
)

# Executors
from .executors import KyaPayBaseExecutor, KyaPayServerExecutor

__all__ = [
    # Extension Constants
    "KYAPAY_EXTENSION_URI",
    # Types
    "KyaPayRequirements",
    "KyaPayToken",
    "KyaPayVerifyResponse",
    "KyaPayChargeResponse",
    "PaymentStatus",
    "KyaPayExtensionConfig",
    # Core Functions
    "create_payment_requirements",
    "create_token",
    "verify_token",
    "charge_token",
    # Utils
    "KyaPayUtils",
    "create_payment_submission_message",
    "extract_task_id",
    # Helpers
    "require_payment",
    "require_payment_choice",
    "paid_service",
    "smart_paid_service",
    "create_tiered_payment_options",
    "check_payment_context",
    # Errors
    "KyaPayErrorCode",
    "KyaPayError",
    "KyaPaymentRequiredException",
    "MessageError",
    "ValidationError",
    "PaymentError",
    "StateError",
    # Extension utilities
    "get_extension_declaration",
    "check_extension_activation",
    "add_extension_activation_header",
    # Agent utilities
    "create_kyapay_agent_card",
    # Executors
    "KyaPayBaseExecutor",
    "KyaPayServerExecutor",
]
