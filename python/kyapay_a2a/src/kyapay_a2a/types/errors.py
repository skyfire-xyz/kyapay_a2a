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
"""Protocol error types and error code mapping."""

from typing import List, Union, Optional, Literal

# Import here to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .kyapay_types import KyaPayRequirements


class KyaPayError(Exception):
    """Base error for kyapay protocol."""
    pass


class MessageError(KyaPayError):
    """Message validation errors."""
    pass


class ValidationError(KyaPayError):
    """Payment validation errors."""
    pass


class PaymentError(KyaPayError):
    """Payment processing errors."""
    pass


class StateError(KyaPayError):
    """State transition errors."""
    pass


class KyaPaymentRequiredException(KyaPayError):
    """Exception thrown to request kyapay payment."""

    def __init__(
        self,
        message: str,
        payment_requirements: Union["KyaPayRequirements", List["KyaPayRequirements"]],
        error_code: Optional[str] = None,
    ):
        super().__init__(message)

        if isinstance(payment_requirements, list):
            self.payment_requirements = payment_requirements
        else:
            self.payment_requirements = [payment_requirements]

        self.error_code = error_code

    def get_accepts_array(self) -> List["KyaPayRequirements"]:
        """Get payment requirements array."""
        return self.payment_requirements

    @classmethod
    def for_service(
        cls,
        price: str,
        seller_service_id: str,
        resource: str,
        description: str = "Payment required for this service",
        token_type: Literal["pay", "kya", "kya+pay"] = "pay",
        identity_permissions: Optional[List[str]] = None,
        message: Optional[str] = None,
    ) -> "KyaPaymentRequiredException":
        """Create payment exception for a service.

        TODO: Re-enable after Task 2.1 (update merchant.py) is complete.
        """
        raise NotImplementedError(
            "for_service() will be enabled after merchant.py is updated (Task 2.1)"
        )


class KyaPayErrorCode:
    """Standard error codes for kyapay."""
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INVALID_TOKEN = "INVALID_TOKEN"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    SERVICE_MISMATCH = "SERVICE_MISMATCH"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    CHARGE_FAILED = "CHARGE_FAILED"
    TOKEN_CREATION_FAILED = "TOKEN_CREATION_FAILED"

    @classmethod
    def get_all_codes(cls) -> List[str]:
        """Returns all defined error codes."""
        return [
            cls.INSUFFICIENT_FUNDS,
            cls.INVALID_TOKEN,
            cls.EXPIRED_TOKEN,
            cls.SERVICE_MISMATCH,
            cls.INVALID_AMOUNT,
            cls.CHARGE_FAILED,
            cls.TOKEN_CREATION_FAILED,
        ]


def map_error_to_code(error: Exception) -> str:
    """Maps implementation errors to spec error codes."""
    error_mapping = {
        ValidationError: KyaPayErrorCode.INVALID_TOKEN,
        PaymentError: KyaPayErrorCode.CHARGE_FAILED,
    }
    return error_mapping.get(type(error), "UNKNOWN_ERROR")
