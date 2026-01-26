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
"""Payment state definitions, metadata keys, and state management types."""

from enum import Enum


class PaymentStatus(str, Enum):
    """Protocol-defined payment states for A2A flow"""

    PAYMENT_REQUIRED = "payment-required"  # Payment requested
    PAYMENT_SUBMITTED = "payment-submitted"  # Payment signed and submitted
    PAYMENT_VERIFIED = "payment-verified"  # Payment has been verified by facilitator
    PAYMENT_REJECTED = "payment-rejected"  # Payment requirements rejected by client
    PAYMENT_COMPLETED = "payment-completed"  # Payment settled successfully
    PAYMENT_FAILED = "payment-failed"  # Payment processing failed


class KyaPayMetadata:
    """Spec-defined metadata key constants"""

    STATUS_KEY = "kyapay.payment.status"
    REQUIRED_KEY = "kyapay.payment.required"  # Contains KyaPaymentRequiredResponse
    PAYLOAD_KEY = "kyapay.payment.payload"  # Contains KyaPayToken
    RECEIPTS_KEY = "kyapay.payment.receipts"  # Contains array of KyaPayChargeResponse objects
    ERROR_KEY = "kyapay.payment.error"  # Error code (when failed)
