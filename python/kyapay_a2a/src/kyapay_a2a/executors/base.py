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
"""Base executor types and interfaces for kyapay payment middleware."""

from abc import ABC, abstractmethod

from ..types import (
    AgentExecutor,
    RequestContext,
    EventQueue,
    KyaPayExtensionConfig,
    KYAPAY_EXTENSION_URI,
)
from ..core.utils import KyaPayUtils


class KyaPayBaseExecutor(ABC):
    """Base executor with kyapay protocol support."""

    def __init__(self, delegate: AgentExecutor, config: KyaPayExtensionConfig):
        """Initialize base executor.

        Args:
            delegate: The underlying agent executor to wrap
            config: kyapay extension configuration
        """
        self._delegate = delegate
        self.config = config
        self.utils = KyaPayUtils()

    def is_active(self, context: RequestContext) -> bool:
        """Check if kyapay extension is activated for this request.

        Args:
            context: Request context containing headers and request info

        Returns:
            True if kyapay extension should be active
        """

        headers = getattr(context, "headers", {})
        if isinstance(headers, dict):
            extensions_header = headers.get("X-A2A-Extensions", "")
            if KYAPAY_EXTENSION_URI in extensions_header:
                return True

        return False

    @abstractmethod
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Execute the agent with kyapay payment middleware.

        Args:
            context: Request context
            event_queue: Event queue for task updates
        """
        ...
