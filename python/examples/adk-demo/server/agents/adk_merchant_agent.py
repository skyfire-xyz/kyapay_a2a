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
import hashlib
try:
    from typing import override
except ImportError:
    def override(method):
        return method
import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from kyapay_a2a.types import KyaPayRequirements

# Import the custom exception and the base agent interface
from .base_agent import BaseAgent
from kyapay_a2a.types import KyaPaymentRequiredException
from kyapay_a2a import KyaPayUtils, get_extension_declaration
from .datasets import DAPPIER_DATASETS
# This is the new, clean ADK Merchant Agent.
# It now implements the BaseAgent interface.





class AdkMerchantAgent(BaseAgent):
    """
    Defines the ADK LlmAgent for the merchant and its corresponding AgentCard.
    The business logic is implemented as tools.
    """

    def __init__(
        self, seller_service_id: str = None
    ):
        self._seller_service_id = seller_service_id or os.getenv("SELLER_SERVICE_ID", "8a507c77-e2da-4847-b339-cca29576d55a")
        self.kyapay = KyaPayUtils()
    
    async def search_datasets(
        self, user_search_query: str
    ) -> None:
        """
        Search the available datasets for one that matches the user query
        """
        print(f"Searching datasets for user search query: {user_search_query}")
        # Return datasets without the 'dataUrl' field
        datasets_no_url = [
            {k: v for k, v in dataset.items() if k != "dataUrl"}
            for dataset in DAPPIER_DATASETS
        ]
        return datasets_no_url

    # Extract the IntentMandate to get the search query

    def _get_dataset_price_and_id(
        self, product_name: str
    ) -> None:
        """
        Get the price for a dataset based on the product name
        """
        print(f"Getting dataset price and id for product name: {product_name}")
        for dataset in DAPPIER_DATASETS:
            if dataset["title"] == product_name:
                return dataset["price"], dataset["id"]
        return None, None
    
    def _get_dataset_resource(self, dataset_id: int) -> str:
        """
        Get the resource for a dataset based on the dataset id
        """
        for dataset in DAPPIER_DATASETS:
            if dataset["id"] == dataset_id:
                return dataset["dataUrl"]
        return None

    def get_datatset_and_request_payment(self, product_name: str) -> dict:
        """
        This is the agent's tool. Instead of returning payment details, it raises
        an exception to signal to the kyapay wrapper that payment is needed.
        """
        if not product_name:
            return {"error": "Product name cannot be empty."}

        price, id = self._get_dataset_price_and_id(product_name)
        # print(f"getting resource", self._get_dataset_resource(id))
        requirements = KyaPayRequirements(
            seller_service_id=self._seller_service_id,
            token_amount=price,
            token_type="pay",
            description=f"Payment for: {product_name}",
            resource=f"/api/dataset/{id}"
        )

        # Signal to the KyaPayServerExecutor that payment is required.
        # The wrapper will catch this and handle the A2A flow.
        raise KyaPaymentRequiredException(product_name, requirements)

    # def before_agent_callback(self, callback_context: CallbackContext):
    #     """
    #     Injects a 'virtual' tool response if payment has been verified.
    #     """
    #     print(f"callback context state: {callback_context.state._value}")
    #     payment_data = callback_context.state.get("payment_verified_data")
    #     print(f"payment data before callback: {payment_data}")
    #     if payment_data:
    #         # Consume the data so it's not used again in the same session.
    #         del callback_context.state["payment_verified_data"]

    #         # Create a Content object that looks like a tool call response.
    #         # This is a structured way to inform the LLM of the payment status.
    #         tool_response = types.Part(
    #             function_response=types.FunctionResponse(
    #                 name="check_payment_status",
    #                 response=payment_data,
    #             )
    #         )
    #         # Set this as the new, overriding input for this turn.
    #         callback_context.new_user_message = types.Content(parts=[tool_response])

    @override
    def create_agent(self) -> LlmAgent:
        """Creates the LlmAgent instance for the merchant."""
        return LlmAgent(
            model="gemini-2.5-flash",
            name="adk_merchant_agent",
            description="An agent that can sell any item by providing a price and then processing the payment using the kyapay protocol.",
            instruction="""You are a helpful and friendly data marketplace merchant agent.
- When a user asks to search for or buy a dataset, first use the `search_datasets` tool to find matching datasets.
- When the user selects a dataset to purchase, use the `get_datatset_and_request_payment` tool.
- If you receive a successful result from the `check_payment_status` tool with a 'resource' field, you MUST provide the user with that exact download URL. This is the actual paid resource they purchased.
- IMPORTANT: Do NOT make up or hallucinate URLs. Always use the exact 'resource' from the check_payment_status response.
- If the system tells you the payment failed, relay the error clearly and politely.
""",
            tools=[self.search_datasets, self.get_datatset_and_request_payment],
            # before_agent_callback=self.before_agent_callback,
        )

    @override
    def create_agent_card(self, url: str) -> AgentCard:
        """Creates the AgentCard for this agent."""
        skills = [
            AgentSkill(
                id="get_dataset_payment_info",
                name="Get Dataset Payment Info",
                description="Provides the price and kyapay payment requirements for any dataset in internal datastore.",
                tags=["pricing", "datasets", "kyapay", "merchant"],
                examples=[
                    "How much for the US Automobile Data - 2024 dataset? If under my budget of $0.005, then proceed with purchasing.",
                    "Buy me the US Automobile Data - 2025 dataset.",
                ],
            )
        ]
        return AgentCard(
            name="KyaPay Merchant Agent",
            description="This agent sells items using the kyapay payment protocol.",
            url=url,
            version="5.0.0",
            defaultInputModes=["text", "text/plain"],
            defaultOutputModes=["text", "text/plain"],
            capabilities=AgentCapabilities(
                streaming=False,
                extensions=[
                    get_extension_declaration(
                        description="Supports payments using the kyapay protocol.",
                        required=True,
                    )
                ],
            ),
            skills=skills,
        )
