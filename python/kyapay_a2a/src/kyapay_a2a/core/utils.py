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
"""State management utilities for kyapay protocol."""

import logging
import uuid
from typing import Optional
from a2a.types import TextPart, Part, Role
from ..types import (
    Task,
    Message,
    PaymentStatus,
    KyaPayMetadata,
    KyaPaymentRequiredResponse,
    KyaPayToken,
    KyaPayChargeResponse,
    TaskState,
    TaskStatus,
)


def _parse_payment_token(token_data: dict) -> KyaPayToken:
    """Parse the payment token using the top-level Pydantic model."""
    # The KyaPayToken model contains the JWT token string
    return KyaPayToken.model_validate(token_data)


def create_payment_submission_message(
    task_id: str,
    payment_token: KyaPayToken,
    text: str = "Payment authorization provided",
    message_id: Optional[str] = None,
) -> Message:
    """Creates correlated payment submission message per spec.

    Args:
        task_id: Task ID for correlation
        payment_token: Payment token to include
        text: Message text content
        message_id: Optional specific message ID; generates UUID if not provided
    """
    msg_id = message_id if message_id is not None else str(uuid.uuid4())
    return Message(
        message_id=msg_id,  # Use provided ID or generate UUID
        task_id=task_id,  # Spec mandates this correlation
        role=Role.user,
        parts=[Part(root=TextPart(kind="text", text=text))],
        metadata={
            KyaPayMetadata.STATUS_KEY: PaymentStatus.PAYMENT_SUBMITTED.value,
            KyaPayMetadata.PAYLOAD_KEY: payment_token.model_dump(by_alias=True),
        },
    )


def extract_task_id(message: Message) -> Optional[str]:
    """Extracts task ID for correlation from payment message."""
    if isinstance(message, dict):
        return message.get("task_id")
    return getattr(message, "task_id", None)


class KyaPayUtils:
    """Core utilities for kyapay protocol state management."""

    STATUS_KEY = KyaPayMetadata.STATUS_KEY
    REQUIRED_KEY = KyaPayMetadata.REQUIRED_KEY
    PAYLOAD_KEY = KyaPayMetadata.PAYLOAD_KEY
    RECEIPTS_KEY = KyaPayMetadata.RECEIPTS_KEY
    ERROR_KEY = KyaPayMetadata.ERROR_KEY

    def get_payment_status_from_message(
        self, message: Message
    ) -> Optional[PaymentStatus]:
        """Extract payment status from message metadata."""
        if not message or not hasattr(message, "metadata") or not message.metadata:
            return None

        status_value = message.metadata.get(self.STATUS_KEY)
        if status_value:
            try:
                return PaymentStatus(status_value)
            except ValueError:
                return None
        return None

    def get_payment_status_from_task(self, task: Task) -> Optional[PaymentStatus]:
        """Extract payment status from task's status message metadata."""
        if not task or not hasattr(task, "status") or not task.status:
            return None
        if not hasattr(task.status, "message") or not task.status.message:
            return None

        return self.get_payment_status_from_message(task.status.message)

    def get_payment_status(self, task: Task) -> Optional[PaymentStatus]:
        """Extract payment status from task metadata (updated to use task status message)."""
        return self.get_payment_status_from_task(task)

    def get_payment_requirements_from_message(
        self, message: Message
    ) -> Optional[KyaPaymentRequiredResponse]:
        """Extract payment requirements from message metadata."""
        if not message or not hasattr(message, "metadata") or not message.metadata:
            return None

        req_data = message.metadata.get(self.REQUIRED_KEY)
        if req_data:
            try:
                return KyaPaymentRequiredResponse.model_validate(req_data)
            except Exception:
                return None
        return None

    def get_payment_requirements_from_task(
        self, task: Task
    ) -> Optional[KyaPaymentRequiredResponse]:
        """Extract payment requirements from task's status message metadata."""
        if not task or not hasattr(task, "status") or not task.status:
            return None
        if not hasattr(task.status, "message") or not task.status.message:
            return None

        return self.get_payment_requirements_from_message(task.status.message)

    def get_payment_requirements(
        self, task: Task
    ) -> Optional[KyaPaymentRequiredResponse]:
        """Extract payment requirements from task metadata (updated to use task status message)."""
        return self.get_payment_requirements_from_task(task)

    def get_payment_token_from_message(
        self, message: Message
    ) -> Optional[KyaPayToken]:
        """Extract payment token from message metadata."""
        if not message or not hasattr(message, "metadata") or not message.metadata:
            return None

        token_data = message.metadata.get(self.PAYLOAD_KEY)
        if token_data:
            try:
                return _parse_payment_token(token_data)
            except Exception as e:
                logging.error(f"Failed to parse payment token: {e}", exc_info=True)
                return None
        return None

    def get_payment_token_from_task(self, task: Task) -> Optional[KyaPayToken]:
        """Extract payment token from task's status message metadata."""
        if not task or not hasattr(task, "status") or not task.status:
            return None
        if not hasattr(task.status, "message") or not task.status.message:
            return None

        return self.get_payment_token_from_message(task.status.message)

    def get_payment_token(self, task: Task) -> Optional[KyaPayToken]:
        """Extract payment token from task metadata (updated to use task status message)."""
        return self.get_payment_token_from_task(task)

    def create_payment_required_task(
        self, task: Task, payment_required: KyaPaymentRequiredResponse
    ) -> Task:
        """Set task to payment required state with proper metadata."""
        # Set task status to input-required as per A2A spec
        if task.status:
            task.status.state = TaskState.input_required
        else:
            task.status = TaskStatus(state=TaskState.input_required)

        # Ensure task has a status message for metadata
        if not hasattr(task.status, "message") or not task.status.message:
            task.status.message = Message(
                message_id=f"{task.id}-status",
                role=Role.agent,
                parts=[
                    Part(
                        root=TextPart(
                            kind="text", text="Payment is required for this service."
                        )
                    )
                ],
                metadata={},
            )

        # Ensure message has metadata
        if (
            not hasattr(task.status.message, "metadata")
            or not task.status.message.metadata
        ):
            task.status.message.metadata = {}

        task.status.message.metadata[self.STATUS_KEY] = (
            PaymentStatus.PAYMENT_REQUIRED.value
        )
        task.status.message.metadata[self.REQUIRED_KEY] = payment_required.model_dump(
            by_alias=True
        )
        return task

    def record_payment_verified(
        self,
        task: Task,
    ) -> Task:
        """Record payment verification in task metadata."""
        # Ensure task has a status message for metadata
        if not hasattr(task.status, "message") or not task.status.message:
            task.status.message = Message(
                message_id=f"{task.id}-status",
                role=Role.agent,
                parts=[
                    Part(
                        root=TextPart(
                            kind="text", text="Payment verification recorded."
                        )
                    )
                ],
                metadata={},
            )

        # Ensure message has metadata
        if (
            not hasattr(task.status.message, "metadata")
            or not task.status.message.metadata
        ):
            task.status.message.metadata = {}

        task.status.message.metadata[self.STATUS_KEY] = (
            PaymentStatus.PAYMENT_VERIFIED.value
        )
        return task

    def record_payment_success(
        self, task: Task, charge_response: KyaPayChargeResponse
    ) -> Task:
        """Record successful payment with charge response."""
        # Ensure task has a status message for metadata
        if not hasattr(task.status, "message") or not task.status.message:
            task.status.message = Message(
                message_id=f"{task.id}-status",
                role=Role.agent,
                parts=[
                    Part(
                        root=TextPart(
                            kind="text", text="Payment completed successfully."
                        )
                    )
                ],
                metadata={},
            )

        # Ensure message has metadata
        if (
            not hasattr(task.status.message, "metadata")
            or not task.status.message.metadata
        ):
            task.status.message.metadata = {}

        task.status.message.metadata[self.STATUS_KEY] = (
            PaymentStatus.PAYMENT_COMPLETED.value
        )
        # Append to receipts array (spec requirement for complete history)
        if self.RECEIPTS_KEY not in task.status.message.metadata:
            task.status.message.metadata[self.RECEIPTS_KEY] = []
        task.status.message.metadata[self.RECEIPTS_KEY].append(
            charge_response.model_dump(by_alias=True)
        )
        # Clean up intermediate data
        task.status.message.metadata.pop(self.PAYLOAD_KEY, None)
        task.status.message.metadata.pop(self.REQUIRED_KEY, None)
        return task

    def record_payment_failure(
        self, task: Task, error_code: str, charge_response: KyaPayChargeResponse
    ) -> Task:
        """Record payment failure with error details."""
        # Set task state to failed
        task.status.state = TaskState.failed

        # Ensure task has a status message for metadata
        if not hasattr(task.status, "message") or not task.status.message:
            task.status.message = Message(
                message_id=f"{task.id}-status",
                role=Role.agent,
                parts=[Part(root=TextPart(kind="text", text="Payment failed."))],
                metadata={},
                context_id=task.context_id,  # Propagate context_id from task
            )

        # Ensure message has metadata
        if (
            not hasattr(task.status.message, "metadata")
            or not task.status.message.metadata
        ):
            task.status.message.metadata = {}

        task.status.message.metadata[self.STATUS_KEY] = (
            PaymentStatus.PAYMENT_FAILED.value
        )
        
        task.status.message.metadata[self.ERROR_KEY] = error_code
        # Append to receipts array (spec requirement for complete history)
        if self.RECEIPTS_KEY not in task.status.message.metadata:
            task.status.message.metadata[self.RECEIPTS_KEY] = []
        task.status.message.metadata[self.RECEIPTS_KEY].append(
            charge_response.model_dump(by_alias=True)
        )
        # Clean up intermediate data
        task.status.message.metadata.pop(self.PAYLOAD_KEY, None)
    
        return task

    def get_payment_receipts_from_message(
        self, message: Message
    ) -> list[KyaPayChargeResponse]:
        """Get all payment receipts from message metadata."""
        if not message or not hasattr(message, "metadata") or not message.metadata:
            return []

        receipts_data = message.metadata.get(self.RECEIPTS_KEY, [])
        receipts = []
        for receipt_data in receipts_data:
            try:
                receipts.append(KyaPayChargeResponse.model_validate(receipt_data))
            except Exception:
                continue
        return receipts

    def get_payment_receipts_from_task(self, task: Task) -> list[KyaPayChargeResponse]:
        """Get all payment receipts from task's status message metadata."""
        if not task or not hasattr(task, "status") or not task.status:
            return []
        if not hasattr(task.status, "message") or not task.status.message:
            return []

        return self.get_payment_receipts_from_message(task.status.message)

    def get_payment_receipts(self, task: Task) -> list[KyaPayChargeResponse]:
        """Get all payment receipts from task metadata (updated to use task status message)."""
        return self.get_payment_receipts_from_task(task)

    def get_latest_receipt(self, task: Task) -> Optional[KyaPayChargeResponse]:
        """Get the most recent payment receipt from task metadata."""
        receipts = self.get_payment_receipts(task)
        return receipts[-1] if receipts else None
