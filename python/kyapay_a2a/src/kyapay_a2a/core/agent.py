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
"""Agent utilities for creating kyapay-enabled agent cards."""

from typing import List, Optional
from a2a.types import AgentCard, AgentCapabilities, AgentExtension

from ..types import KyaPayExtensionConfig, KYAPAY_EXTENSION_URI


def create_kyapay_agent_card(
    name: str,
    description: str,
    url: str,
    version: str = "1.0.0",
    extensions_config: Optional[KyaPayExtensionConfig] = None,
    skills: Optional[List] = None,
    instructions: Optional[List[str]] = None,
    model: Optional[str] = None,
    default_input_modes: Optional[List[str]] = None,
    default_output_modes: Optional[List[str]] = None,
    streaming: bool = True,
) -> AgentCard:
    """Create an AgentCard with kyapay extension capabilities.

    Args:
        name: Name of the agent
        description: Description of the agent
        url: The URL where this agent can be reached
        version: Agent version (default: "1.0.0")
        extensions_config: kyapay extension configuration (optional)
        skills: List of agent skills (optional)
        instructions: List of agent instructions (optional)
        model: Model name (optional)
        default_input_modes: Supported input modes
        default_output_modes: Supported output modes
        streaming: Whether streaming is supported

    Returns:
        AgentCard with kyapay extension capabilities
    """
    # Default input/output modes
    if default_input_modes is None:
        default_input_modes = ["text", "text/plain"]
    if default_output_modes is None:
        default_output_modes = ["text", "text/plain"]
    if skills is None:
        skills = []

    # Create base capabilities
    capabilities = AgentCapabilities(
        streaming=streaming,
        extensions=[
            AgentExtension(
                uri=KYAPAY_EXTENSION_URI,
                description="Supports payments using the kyapay protocol.",
                required=True,
            )
        ],
    )

    # Create the agent card data
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version=version,
        default_input_modes=default_input_modes,
        default_output_modes=default_output_modes,
        capabilities=capabilities,
        skills=skills,
    )
