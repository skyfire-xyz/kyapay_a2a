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
import pytest
from unittest.mock import AsyncMock, MagicMock

from a2a.types import Task, Message, TaskState, TaskStatus, TextPart, Part
from kyapay_a2a.executors.server import KyaPayServerExecutor
from kyapay_a2a.types import (
    PaymentStatus,
    KyaPayMetadata,
    KyaPaymentRequiredResponse,
    KyaPayToken,
    KyaPayRequirements,
    KyaPayVerifyResponse,
    KyaPayChargeResponse,
)
from kyapay_a2a.core.utils import KyaPayUtils

# --- Fixtures ---


@pytest.fixture
def utils():
    """Returns an instance of KyaPayUtils."""
    return KyaPayUtils()


@pytest.fixture
def sample_task():
    """Returns a sample Task object."""
    return Task(
        id="task-123",
        contextId="context-456",
        status=TaskStatus(state=TaskState.working),
    )


@pytest.fixture
def sample_payment_requirements():
    """Returns a sample KyaPayRequirements object."""
    return KyaPayRequirements(
        seller_service_id="5e7f3359-9ec1-4078-bf45-401d079af1be",
        token_amount="0.050",
        token_type="pay",
        description="Test Payment for API Access",
        resource="/api/test",
    )


@pytest.fixture
def sample_payment_token():
    """Returns a sample KyaPayToken object."""
    return KyaPayToken(
        token="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.test",
        token_type="pay",
        buyer_tag="test-buyer",
    )


# --- Tests for KyaPayUtils ---


def test_create_payment_required_task(utils, sample_task, sample_payment_requirements):
    """
    Tests that `create_payment_required_task` correctly updates the task's
    status and metadata.
    """
    payment_required_response = KyaPaymentRequiredResponse(
        kyapay_version=1,
        accepts=[sample_payment_requirements],
        error=None,
    )

    updated_task = utils.create_payment_required_task(
        sample_task, payment_required_response
    )

    assert updated_task.status.state == TaskState.input_required
    assert (
        updated_task.status.message.metadata[KyaPayMetadata.STATUS_KEY]
        == PaymentStatus.PAYMENT_REQUIRED.value
    )
    assert updated_task.status.message.metadata[KyaPayMetadata.REQUIRED_KEY] is not None


def test_get_payment_token_from_message(utils, sample_payment_token):
    """
    Tests that `get_payment_token_from_message` correctly parses a
    KyaPayToken from a message's metadata.
    """
    message = Message(
        messageId="msg-1",
        role="user",
        parts=[Part(root=TextPart(text="test"))],
        metadata={
            KyaPayMetadata.PAYLOAD_KEY: sample_payment_token.model_dump(by_alias=True)
        },
    )

    extracted_token = utils.get_payment_token_from_message(message)
    assert isinstance(extracted_token, KyaPayToken)
    assert extracted_token.token_type == "pay"
    assert extracted_token.buyer_tag == "test-buyer"


def test_get_payment_requirements_from_task(utils, sample_task, sample_payment_requirements):
    """
    Tests that `get_payment_requirements` correctly extracts payment requirements
    from a task's metadata.
    """
    payment_required_response = KyaPaymentRequiredResponse(
        kyapay_version=1,
        accepts=[sample_payment_requirements],
    )

    # Create a task with payment requirements in metadata
    sample_task.status = TaskStatus(
        state=TaskState.input_required,
        message=Message(
            messageId="msg-1",
            role="agent",
            parts=[Part(root=TextPart(text="Payment required"))],
            metadata={
                KyaPayMetadata.REQUIRED_KEY: payment_required_response.model_dump(by_alias=True)
            }
        )
    )

    requirements = utils.get_payment_requirements(sample_task)
    assert requirements is not None
    assert len(requirements.accepts) == 1
    assert requirements.accepts[0].seller_service_id == "5e7f3359-9ec1-4078-bf45-401d079af1be"
    assert requirements.accepts[0].token_amount == "0.050"


def test_get_payment_status(utils, sample_task):
    """
    Tests that `get_payment_status` correctly extracts payment status from task metadata.
    """
    sample_task.status = TaskStatus(
        state=TaskState.completed,
        message=Message(
            messageId="msg-1",
            role="agent",
            parts=[Part(root=TextPart(text="Payment completed"))],
            metadata={
                KyaPayMetadata.STATUS_KEY: PaymentStatus.PAYMENT_COMPLETED.value
            }
        )
    )

    status = utils.get_payment_status(sample_task)
    assert status == PaymentStatus.PAYMENT_COMPLETED


# --- Tests for KyaPayServerExecutor ---


class MockConcreteExecutor(KyaPayServerExecutor):
    """A concrete implementation of the abstract KyaPayServerExecutor for testing."""

    async def verify_payment(self, token, requirements):
        return KyaPayVerifyResponse(
            is_valid=True,
            token_data={"sub": "buyer-123", "amount": "0.050"}
        )

    async def charge_payment(self, token, charge_amount):
        return KyaPayChargeResponse(
            success=True,
            amount_charged=charge_amount,
            transaction_id="txn-abc123"
        )


@pytest.mark.asyncio
async def test_server_executor_payment_flow():
    """
    Tests that the KyaPayServerExecutor correctly calls verify and charge
    when it receives a payment-submitted message.
    """
    delegate = AsyncMock()

    # Create executor instance
    executor = MockConcreteExecutor(delegate=delegate, config=MagicMock())
    executor.verify_payment = AsyncMock(
        return_value=KyaPayVerifyResponse(
            is_valid=True,
            token_data={"sub": "buyer-123", "amount": "0.050"}
        )
    )
    executor.charge_payment = AsyncMock(
        return_value=KyaPayChargeResponse(
            success=True,
            amount_charged="0.050",
            transaction_id="txn-abc123"
        )
    )

    # Simulate the context and event queue
    context = MagicMock()
    context.task_id = "task-123"
    context.context_id = "context-456"
    event_queue = AsyncMock()

    # Create a message with a payment token
    payment_token = KyaPayToken(
        token="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.test",
        token_type="pay",
        buyer_tag="test-buyer",
    )
    context.message = Message(
        messageId="msg-1",
        role="user",
        parts=[Part(root=TextPart(text="send_payment_token"))],
        metadata={
            KyaPayMetadata.STATUS_KEY: PaymentStatus.PAYMENT_SUBMITTED.value,
            KyaPayMetadata.PAYLOAD_KEY: payment_token.model_dump(by_alias=True),
        },
    )
    context.current_task = Task(
        id="task-123",
        contextId="context-456",
        status=TaskStatus(state=TaskState.working),
        metadata={},
    )

    # Mock the internal requirement store to simulate a pending payment
    executor._payment_requirements_store[context.current_task.id] = [
        KyaPayRequirements(
            seller_service_id="5e7f3359-9ec1-4078-bf45-401d079af1be",
            token_amount="0.050",
            token_type="pay",
            description="Test Payment",
            resource="/api/test",
        )
    ]

    # Execute the flow
    await executor.execute(context, event_queue)

    # Assert that the correct methods were called
    executor.verify_payment.assert_called_once()
    delegate.execute.assert_called_once()
    executor.charge_payment.assert_called_once()


@pytest.mark.asyncio
async def test_server_executor_invalid_token():
    """
    Tests that the KyaPayServerExecutor handles invalid tokens correctly.
    """
    delegate = AsyncMock()

    executor = MockConcreteExecutor(delegate=delegate, config=MagicMock())
    executor.verify_payment = AsyncMock(
        return_value=KyaPayVerifyResponse(
            is_valid=False,
            invalid_reason="Token signature verification failed"
        )
    )
    executor.charge_payment = AsyncMock()

    context = MagicMock()
    context.task_id = "task-123"
    context.context_id = "context-456"
    event_queue = AsyncMock()

    payment_token = KyaPayToken(
        token="invalid.token.here",
        token_type="pay",
    )
    context.message = Message(
        messageId="msg-1",
        role="user",
        parts=[Part(root=TextPart(text="send_payment_token"))],
        metadata={
            KyaPayMetadata.STATUS_KEY: PaymentStatus.PAYMENT_SUBMITTED.value,
            KyaPayMetadata.PAYLOAD_KEY: payment_token.model_dump(by_alias=True),
        },
    )
    context.current_task = Task(
        id="task-123",
        contextId="context-456",
        status=TaskStatus(state=TaskState.working),
        metadata={},
    )

    executor._payment_requirements_store[context.current_task.id] = [
        KyaPayRequirements(
            seller_service_id="5e7f3359-9ec1-4078-bf45-401d079af1be",
            token_amount="0.050",
            token_type="pay",
            description="Test",
            resource="/test",
        )
    ]

    # Execute the flow
    await executor.execute(context, event_queue)

    # Verify was called but charge should NOT be called due to invalid token
    executor.verify_payment.assert_called_once()
    executor.charge_payment.assert_not_called()
    # Task should be in failed state
    assert context.current_task.status.state == TaskState.failed


def test_kyapay_metadata_keys():
    """
    Tests that KyaPayMetadata has the correct metadata key constants.
    """
    assert KyaPayMetadata.STATUS_KEY == "kyapay.payment.status"
    assert KyaPayMetadata.REQUIRED_KEY == "kyapay.payment.required"
    assert KyaPayMetadata.PAYLOAD_KEY == "kyapay.payment.payload"
    assert KyaPayMetadata.RECEIPTS_KEY == "kyapay.payment.receipts"
    assert KyaPayMetadata.ERROR_KEY == "kyapay.payment.error"


def test_payment_status_values():
    """
    Tests that PaymentStatus enum has the correct values.
    """
    assert PaymentStatus.PAYMENT_REQUIRED.value == "payment-required"
    assert PaymentStatus.PAYMENT_SUBMITTED.value == "payment-submitted"
    assert PaymentStatus.PAYMENT_VERIFIED.value == "payment-verified"
    assert PaymentStatus.PAYMENT_COMPLETED.value == "payment-completed"
    assert PaymentStatus.PAYMENT_FAILED.value == "payment-failed"
