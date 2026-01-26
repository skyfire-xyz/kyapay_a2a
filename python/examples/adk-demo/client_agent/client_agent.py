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
import json
import logging
import uuid
import os

import httpx
from a2a.client import A2ACardResolver
from a2a.types import (
    AgentCard,
    JSONRPCError,
    Message,
    MessageSendParams,
    Part,
    Task,
    TaskState,
    TextPart,
)
from google.adk import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.tool_context import ToolContext

# Local imports
from ._remote_agent_connection import RemoteAgentConnections, TaskUpdateCallback
from kyapay_a2a.core.utils import KyaPayUtils
from kyapay_a2a.core.protocol import create_token
from kyapay_a2a.types import PaymentStatus

logger = logging.getLogger(__name__)


class ClientAgent:
    """
    The orchestrator agent. It discovers other agents and delegates tasks
    to them, managing the conversation flow based on task states.
    """

    def __init__(
        self,
        remote_agent_addresses: list[str],
        http_client: httpx.AsyncClient,
        task_callback: TaskUpdateCallback | None = None,
        skyfire_api_key: str = None,
        skyfire_api_host: str = None,
        buyer_tag: str = None,
    ):
        """Initializes the ClientAgent."""
        self.task_callback = task_callback
        self.httpx_client = http_client
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}
        self.remote_agent_addresses = remote_agent_addresses
        self.agents_info_str = ""
        self._initialized = False
        self.kyapay = KyaPayUtils()

        # Skyfire credentials for token creation
        self.skyfire_api_key = skyfire_api_key or os.getenv("SKYFIRE_API_KEY")
        self.skyfire_api_host = skyfire_api_host or os.getenv("SKYFIRE_API_HOST", "https://api.skyfire.xyz")
        self.buyer_tag = buyer_tag or os.getenv("BUYER_TAG", "default-buyer")

        if not self.skyfire_api_key:
            raise ValueError("SKYFIRE_API_KEY is required for ClientAgent")

    def create_agent(self) -> Agent:
        """Creates the ADK Agent instance."""
        return Agent(
            model="gemini-2.5-flash",
            name="client_agent",
            instruction=self.root_instruction,
            before_agent_callback=self.before_agent_callback,
            description="An orchestrator that delegates tasks to other agents.",
            tools=[self.list_remote_agents, self.send_message],
        )

    # --- Agent Setup and Instructions ---

    def root_instruction(self, context: ReadonlyContext) -> str:
        """Provides the master instruction set for the orchestrator LLM."""
        return f"""
You are a master orchestrator agent. Your job is to complete user requests by delegating tasks to a network of specialized agents.

**Standard Operating Procedure (SOP):**

1.  **Discover**: Always start by using `list_remote_agents` to see which agents are available.
2.  **Delegate**: Send the user's request to the most appropriate agent using `send_message`. For example, if the user wants to buy something, send the request to a merchant agent.
3.  **Confirm Payment**: If the merchant requires a payment, the system will return a confirmation message. You MUST present this message to the user.
4.  **Sign and Send**: If the user confirms they want to pay (e.g., by saying "yes"), you MUST call `send_message` again, targeting the *same agent*, with the exact message: "sign_and_send_payment". The system will handle the signing and sending of the payload.
5.  **Report Outcome**: Clearly report the final success or failure message to the user.

**System Context:**

* **Available Agents**:
    {self.agents_info_str}

Remmeber to start by using the `list_remote_agents` tool to see which agents are available.
"""

    async def before_agent_callback(self, callback_context: CallbackContext):
        """Initializes connections to remote agents before the first turn."""
        if self._initialized:
            return

        for address in self.remote_agent_addresses:
            card = await A2ACardResolver(self.httpx_client, address).get_agent_card()
            self.remote_agent_connections[card.name] = RemoteAgentConnections(
                self.httpx_client, card
            )
            self.cards[card.name] = card

        # Create a formatted string of agent info for the prompt
        agent_list = [
            {"name": c.name, "description": c.description} for c in self.cards.values()
        ]
        self.agents_info_str = json.dumps(agent_list, indent=2)
        self._initialized = True

    # --- Agent Tools ---
    def list_remote_agents(self):
        """Lists the available remote agents that this host can talk to."""
        return [
            {"name": card.name, "description": card.description}
            for card in self.cards.values()
        ]

    async def send_message(
        self, agent_name: str, message: str, tool_context: ToolContext
    ):
        """Sends a message to a named remote agent and handles the response."""
        if agent_name not in self.remote_agent_connections:
            raise ValueError(f"Agent '{agent_name}' not found.")

        state = tool_context.state
        client = self.remote_agent_connections[agent_name]
        task_id = None
        message_metadata = {}

        if message == "sign_and_send_payment":
            # This is the second step: user has confirmed payment.
            purchase_task_data = state.get("purchase_task")
            if not purchase_task_data:
                raise ValueError(
                    "State inconsistency: 'purchase_task' not found to create payment token."
                )

            original_task = Task.model_validate(purchase_task_data)
            task_id = original_task.id

            requirements = self.kyapay.get_payment_requirements(original_task)
            if not requirements:
                raise ValueError(
                    "Could not find payment requirements in the original task."
                )

            # Create payment token via Skyfire API
            payment_token = await create_token(
                requirements=requirements.accepts[0],
                buyer_tag=self.buyer_tag,
                skyfire_api_key=self.skyfire_api_key,
                skyfire_api_host=self.skyfire_api_host,
            )

            message_metadata[self.kyapay.PAYLOAD_KEY] = payment_token.model_dump(
                by_alias=True
            )
            message_metadata[self.kyapay.STATUS_KEY] = (
                PaymentStatus.PAYMENT_SUBMITTED.value
            )

            # The message text to the merchant is a simple confirmation.
            message = "send_payment_token"

        # --- Construct the message with metadata ---
        request = MessageSendParams(
            message=Message(
                messageId=str(uuid.uuid4()),
                role="user",
                parts=[Part(root=TextPart(text=message))],
                contextId=state.get("context_id"),
                taskId=task_id,
                metadata=message_metadata if message_metadata else None,
            )
        )

        # Send the message and wait for the task result
        response_task = await client.send_message(
            request.message.message_id, request, self.task_callback
        )

        print("\n" + "="*80)
        print(f"📨 RECEIVED MESSAGE FROM MERCHANT: {agent_name}")
        print("="*80)

        # --- Handle potential server errors ---
        if isinstance(response_task, JSONRPCError):
            print(f"❌ ERROR Response:")
            print(f"   Code: {response_task.code}")
            print(f"   Message: {response_task.message}")
            print("="*80 + "\n")
            logger.error(
                f"Received JSONRPCError from {agent_name}: {response_task.message}"
            )
            return f"Agent '{agent_name}' returned an error: {response_task.message} (Code: {response_task.code})"

        
        print(f"response_task: {response_task.model_dump_json(indent=2)}")

        
        # Print the full task details
        print(f"📋 Task ID: {response_task.id}")
        print(f"📋 Context ID: {response_task.context_id}")
        print(f"📊 Task State: {response_task.status.state.value}")

        # Print task metadata if present
        if response_task.metadata:
            print(f"\n🏷️  Task Metadata:")
            for key, value in response_task.metadata.items():
                print(f"   {key}: {value}")

        # Print message metadata if present
        if response_task.status.message and response_task.status.message.metadata:
            print(f"\n💬 Message Metadata:")
            for key, value in response_task.status.message.metadata.items():
                if key == "kyapay.payment.required":
                    print(f"   {key}: [Payment Requirements Object]")
                elif key == "kyapay.payment.receipts":
                    print(f"   {key}: [Payment Receipts Array - {len(value)} receipt(s)]")
                else:
                    print(f"   {key}: {value}")

        # Print artifacts if present
        if response_task.artifacts:
            print(f"\n📎 Artifacts ({len(response_task.artifacts)}):")
            for i, artifact in enumerate(response_task.artifacts):
                for part in artifact.parts:
                    part_root = part.root
                    if isinstance(part_root, TextPart):
                        text_preview = part_root.text[:100] + "..." if len(part_root.text) > 100 else part_root.text
                        print(f"   [{i}] Text: {text_preview}")

        print("="*80 + "\n")

        # Update state with the latest task info
        state["context_id"] = response_task.context_id
        state["last_contacted_agent"] = agent_name

        # --- Handle Response Based on Task State ---
        if response_task.status.state == TaskState.input_required:
            # The merchant requires payment. Store the task and ask the user for confirmation.
            state["purchase_task"] = response_task.model_dump(by_alias=True)
            requirements = self.kyapay.get_payment_requirements(response_task)

            if not requirements:
                raise ValueError("Server requested payment but sent no requirements.")

            if not requirements.accepts:
                raise ValueError(
                    "Server requested payment but sent no valid payment options."
                )

            # Extract details for the confirmation message.
            payment_option = requirements.accepts[0]
            amount = payment_option.token_amount
            description = payment_option.description

            return f"The merchant is requesting payment: {description} for {amount} USDC. Do you want to approve this payment?"

        elif response_task.status.state in (TaskState.completed, TaskState.failed):
            # The task is finished. Report the outcome.
            final_text = []
            if response_task.artifacts:
                for artifact in response_task.artifacts:
                    for part in artifact.parts:
                        part_root = part.root
                        if isinstance(part_root, TextPart):
                            final_text.append(part_root.text)

            if final_text:
                return " ".join(final_text)

            # Check payment status for specific feedback
            payment_status = self.kyapay.get_payment_status(response_task)

            if payment_status == PaymentStatus.PAYMENT_COMPLETED:
                return "Payment successful! Your purchase is complete."

            if payment_status == PaymentStatus.PAYMENT_FAILED:
                # Get error details from metadata
                error_code = None
                error_reason = None
                if response_task.status.message and response_task.status.message.metadata:
                    error_code = response_task.status.message.metadata.get("kyapay.payment.error")
                    receipts = response_task.status.message.metadata.get("kyapay.payment.receipts", [])
                    if receipts:
                        error_reason = receipts[-1].get("error_reason")

                error_msg = "Payment failed."
                if error_reason:
                    error_msg += f" Reason: {error_reason}"
                if error_code:
                    error_msg += f" (Error code: {error_code})"
                return error_msg

            return f"Task with {agent_name} is {response_task.status.state.value}."

        else:
            # Handle other states like 'working'
            return f"Task with {agent_name} is now in state: {response_task.status.state.value}"
