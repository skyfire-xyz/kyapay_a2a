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
"""Server-side executor for merchant implementations."""

import logging
from abc import ABCMeta, abstractmethod
from typing import Optional, Dict, List

from a2a.server.tasks import TaskUpdater

from .base import KyaPayBaseExecutor
from ..types import (
    AgentExecutor,
    RequestContext,
    EventQueue,
    PaymentStatus,
    KyaPayRequirements,
    KyaPayChargeResponse,
    KyaPayExtensionConfig,
    KyaPayErrorCode,
    KyaPaymentRequiredException,
    KyaPayToken,
    Task,
    TaskStatus,
    TaskState,
    KyaPaymentRequiredResponse,
    KyaPayVerifyResponse,
)


logger = logging.getLogger(__name__)


class KyaPayServerExecutor(KyaPayBaseExecutor, metaclass=ABCMeta):
    """Server-side payment middleware for merchant agents.

    Exception-based payment requirements:
    Delegate agents throw KyaPaymentRequiredException to request payment dynamically.

    Example:
        # Create executor
        server = KyaPayServerExecutor(my_agent, config)

        # In your delegate agent:
        raise KyaPaymentRequiredException.for_service(
            price="0.005",
            seller_service_id="5e7f3359-9ec1-4078-bf45-401d079af1be",
            resource="/premium-feature"
        )
    """

    def __init__(
        self,
        delegate: AgentExecutor,
        config: KyaPayExtensionConfig,
    ):
        """Initialize server executor.

        Args:
            delegate: Underlying agent executor for business logic
            config: kyapay extension configuration
        """
        super().__init__(delegate, config)
        self._payment_requirements_store: Dict[str, List[KyaPayRequirements]] = {}

    @abstractmethod
    async def verify_payment(
        self, token: KyaPayToken, requirements: KyaPayRequirements
    ) -> KyaPayVerifyResponse:
        """Verifies the payment token (JWT verification)."""
        raise NotImplementedError

    @abstractmethod
    async def charge_payment(
        self, token: KyaPayToken, charge_amount: str
    ) -> KyaPayChargeResponse:
        """Charges the payment token via Skyfire API."""
        raise NotImplementedError

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Payment middleware: verify → execute service → settle."""
        if not context.task_id or not context.context_id:
            raise ValueError("Task ID and Context ID cannot be None")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await updater.submit()
        await updater.start_work()

        task = context.current_task or Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.working),
        )
        self.utils.get_payment_status(task)

        payment_status_task = (
            self.utils.get_payment_status_from_task(context.current_task)
            if context.current_task
            else None
        )
        payment_status_message = (
            self.utils.get_payment_status_from_message(context.message)
            if context.message
            else None
        )

        if (
            payment_status_task == PaymentStatus.PAYMENT_SUBMITTED
            or payment_status_message == PaymentStatus.PAYMENT_SUBMITTED
        ):
            return await self._process_paid_request(context, event_queue)

        try:
            return await self._delegate.execute(context, event_queue)
        except KyaPaymentRequiredException as e:
            await self._handle_payment_required_exception(e, context, event_queue)
            return

    async def _process_paid_request(
        self, context: RequestContext, event_queue: EventQueue
    ):
        """Process paid request: verify → execute → charge."""
        logger.info("Starting payment processing...")
        task = context.current_task
        if not task:
            logger.error("Task not found in context during payment processing.")
            raise ValueError("Task not found in context")

        logger.info(
            f"✅ Received payment token. Beginning verification for task: {task.id}"
        )

        payment_token = (
            self.utils.get_payment_token(task)
            or self.utils.get_payment_token_from_message(context.message)
            if context.message
            else None
        )
        if not payment_token:
            logger.warning(
                "Payment token missing from both task and message metadata."
            )
            return await self._fail_payment(
                task,
                KyaPayErrorCode.INVALID_TOKEN,
                "Missing payment token",
                event_queue,
            )

        logger.info(
            f"Retrieved payment token: {payment_token.model_dump_json(indent=2)}"
        )

        logger.info(
            f"Attempting to retrieve payment requirements for task ID: {task.id}"
        )
        payment_requirements = self._extract_payment_requirements_from_context(
            task, context
        )
        if not payment_requirements:
            logger.warning("Payment requirements missing from context.")
            return await self._fail_payment(
                task,
                KyaPayErrorCode.INVALID_TOKEN,
                "Missing payment requirements",
                event_queue,
            )

        logger.info(
            f"Retrieved payment requirements: {payment_requirements.model_dump_json(indent=2)}"
        )

        try:
            logger.info("Calling self.verify_payment...")
            verify_response = await self.verify_payment(
                payment_token, payment_requirements
            )
            logger.info(
                f"Verification response: {verify_response.model_dump_json(indent=2)}"
            )
            if not verify_response.is_valid:
                logger.warning(
                    f"Payment verification failed: {verify_response.invalid_reason}"
                )
                return await self._fail_payment(
                    task,
                    KyaPayErrorCode.INVALID_TOKEN,
                    verify_response.invalid_reason or "Invalid payment",
                    event_queue,
                )
        except Exception as e:
            logger.error(f"Exception during payment verification: {e}", exc_info=True)
            return await self._fail_payment(
                task,
                KyaPayErrorCode.INVALID_TOKEN,
                f"Verification failed: {e}",
                event_queue,
            )

        logger.info("Payment verified successfully. Recording and updating task.")
        task = self.utils.record_payment_verified(task)
        await event_queue.enqueue_event(task)

        # Add the verification status to the task metadata for the delegate agent.
        if not task.metadata:
            task.metadata = {}
        task.metadata["kyapay_payment_verified"] = True
        logger.info("Set kyapay_payment_verified=True in task.metadata")

        if task.status.message is not None and (
            not hasattr(task.status.message, "metadata")
            or not task.status.message.metadata
        ):
            task.status.message.metadata = {}

        # Add the payment requirements to the task metadata so the delegate can access them
        # (e.g., to get the product description)
        task.status.message.metadata[self.utils.REQUIRED_KEY] = KyaPaymentRequiredResponse(
            kyapay_version=1,
            accepts=[payment_requirements],
        ).model_dump(by_alias=True)
        logger.info(f"Added payment requirements to task.status.message.metadata: {task.status.message.metadata}")

        #charge the payment
        try:
            logger.info("Calling self.charge_payment...")
            charge_response = await self.charge_payment(
                payment_token, payment_requirements.token_amount
            )
            logger.info(
                f"Charge response: {charge_response.model_dump_json(indent=2)}"
            )
            if charge_response.success:
                logger.info("Charge successful. Recording payment success.")
                task = self.utils.record_payment_success(task, charge_response)

                self._payment_requirements_store.pop(task.id, None)
            else:
                logger.warning(f"Charge failed: {charge_response.error_reason}")
                error_code = (
                    KyaPayErrorCode.INSUFFICIENT_FUNDS
                    if "insufficient" in (charge_response.error_reason or "").lower()
                    else KyaPayErrorCode.SETTLEMENT_FAILED
                )
                task = self.utils.record_payment_failure(
                    task, error_code, charge_response
                )

                self._payment_requirements_store.pop(task.id, None)
            await event_queue.enqueue_event(task)
            logger.info("Charge processing finished.")
        except Exception as e:
            logger.error(f"Exception during charge: {e}", exc_info=True)
            return await self._fail_payment(
                task,
                KyaPayErrorCode.SETTLEMENT_FAILED,
                f"Charge failed: {e}",
                event_queue,
            )
        
        # Only execute the delegate agent AFTER successful charge
        # Re-add the payment requirements to metadata (record_payment_success removes them as "cleanup")
        # The delegate agent needs access to the resource URL to deliver it to the user
        task.status.message.metadata[self.utils.REQUIRED_KEY] = KyaPaymentRequiredResponse(
            kyapay_version=1,
            accepts=[payment_requirements],
        ).model_dump(by_alias=True)
        logger.info(f"Re-added payment requirements for delegate. Resource: {payment_requirements.resource}")
        
        try:
            logger.info("Payment charged successfully. Executing delegate agent to deliver resource...")
            await self._delegate.execute(context, event_queue)
            logger.info("Delegate agent execution finished. Transaction complete.")
        except Exception as e:
            # Note: Payment was already charged, so this is a delivery failure, not a payment failure
            logger.error(f"Exception during delegate execution (payment already charged): {e}", exc_info=True)
            # We don't fail the payment here since the charge already succeeded
            # The user paid but delivery failed - this needs manual resolution


    def _extract_payment_requirements_from_context(
        self, task: Task, context: RequestContext
    ) -> Optional[KyaPayRequirements]:
        """
        Extracts the payment requirements from the stored list.
        For kyapay, we simply return the first requirement (no scheme/network matching needed).
        """
        accepts_array = self._payment_requirements_store.get(task.id)
        if not accepts_array:
            logger.warning(
                f"No payment requirements found in store for task ID: {task.id}"
            )
            return None

        # For kyapay, just return the first requirement
        # (multiple options would have different seller_service_id or resource)
        logger.info("Retrieved payment requirements from store.")
        return accepts_array[0] if accepts_array else None

    async def _handle_payment_required_exception(
        self,
        exception: KyaPaymentRequiredException,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        """Handle KyaPaymentRequiredException to request payment.

        Extracts payment requirements directly from the exception and creates
        a payment required response for the client.
        """
        task = context.current_task
        if not task:
            # If the task object isn't in the context (e.g., on the first turn),
            # create a temporary one using the IDs from the context. The TaskManager
            # will find the real task using the ID.
            if not context.task_id or not context.context_id:
                raise ValueError(
                    "Cannot handle payment exception: task_id or context_id is missing from the context."
                )

            task = Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.input_required),
                metadata={},
            )
        else:
            # Ensure the existing task is always in the input_required state
            task.status.state = TaskState.input_required

        # Extract payment requirements directly from the exception
        accepts_array = exception.get_accepts_array()

        # Store payment requirements for later correlation
        self._payment_requirements_store[task.id] = accepts_array

        # Only set error field if there's an actual error code (not just a description)
        payment_required = KyaPaymentRequiredResponse(
            kyapay_version=1,
            accepts=accepts_array,
            error=str(exception) if exception.error_code else None,
        )

        # Update task with payment requirements
        task = self.utils.create_payment_required_task(task, payment_required)

        # Send the payment required response
        await event_queue.enqueue_event(task)

    async def _fail_payment(
        self, task, error_code: str, error_reason: str, event_queue: EventQueue
    ):
        """Handle payment failure."""
        failure_response = KyaPayChargeResponse(
            success=False, error_reason=error_reason
        )
        print(f"failure_response: {failure_response.model_dump_json(indent=2)}")
        task = self.utils.record_payment_failure(task, error_code, failure_response)

        self._payment_requirements_store.pop(task.id, None)
        print(f"task state before returning: {task.model_dump_json(indent=2)}")
        # Use TaskUpdater to properly send a TaskStatusUpdateEvent with final=True
        # This ensures the client receives the failed status correctly
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            TaskState.failed,
            message=updater.new_agent_message(
                parts=task.status.message.parts,
                metadata=task.status.message.metadata,
            ),
        )
        print("task updated with TaskUpdater.update_status(failed)")
