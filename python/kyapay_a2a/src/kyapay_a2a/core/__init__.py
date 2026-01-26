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
"""Core package exports for kyapay integration."""

from .merchant import create_payment_requirements
from .protocol import create_token, verify_token, charge_token
from .utils import KyaPayUtils, create_payment_submission_message, extract_task_id
from .helpers import (
    require_payment,
    require_payment_choice,
    paid_service,
    smart_paid_service,
    create_tiered_payment_options,
    check_payment_context,
)
from .agent import create_kyapay_agent_card

__all__ = [
    # Core merchant functions
    "create_payment_requirements",
    # Protocol functions (buyer + seller)
    "create_token",      # Buyer: create kyapay token
    "verify_token",      # Seller: verify JWT token
    "charge_token",      # Seller: charge token via Skyfire API
    # Utilities
    "KyaPayUtils",
    "create_payment_submission_message",
    "extract_task_id",
    # Helper functions
    "require_payment",
    "require_payment_choice",
    "paid_service",
    "smart_paid_service",
    "create_tiered_payment_options",
    "check_payment_context",
    # Agent utilities
    "create_kyapay_agent_card",
]
