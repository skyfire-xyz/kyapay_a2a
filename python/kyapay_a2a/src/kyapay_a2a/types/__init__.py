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
"""Types package for kyapay_a2a - re-exports A2A SDK types, adds kyapay-specific extensions."""

from a2a.types import (
    Task,
    Message,
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    TaskState,
    TaskStatus,
)
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue

# Kyapay types
from .kyapay_types import (
    KyaPayRequirements,
    KyaPayToken,
    KyaPayVerifyResponse,
    KyaPayChargeResponse,
    KyaPaymentRequiredResponse,
    TokenAmount,
)

from .state import PaymentStatus, KyaPayMetadata

from .errors import (
    KyaPayError,
    MessageError,
    ValidationError,
    PaymentError,
    StateError,
    KyaPaymentRequiredException,
    KyaPayErrorCode,
    map_error_to_code,
)

from .config import (
    KYAPAY_EXTENSION_URI,
    KyaPayExtensionConfig,
    KyaPayServerConfig,
)

from ..extension import (
    get_extension_declaration,
    check_extension_activation,
    add_extension_activation_header,
)

__all__ = [
    # A2A SDK types
    "Task",
    "Message",
    "AgentCard",
    "AgentCapabilities",
    "AgentSkill",
    "TaskState",
    "TaskStatus",
    "AgentExecutor",
    "RequestContext",
    "EventQueue",
    # Kyapay types
    "KyaPayRequirements",
    "KyaPayToken",
    "KyaPayVerifyResponse",
    "KyaPayChargeResponse",
    "KyaPaymentRequiredResponse",
    "TokenAmount",
    "PaymentStatus",
    "KyaPayMetadata",
    # Error types
    "KyaPayError",
    "MessageError",
    "ValidationError",
    "PaymentError",
    "StateError",
    "KyaPaymentRequiredException",
    "KyaPayErrorCode",
    "map_error_to_code",
    # Config types
    "KYAPAY_EXTENSION_URI",
    "KyaPayExtensionConfig",
    "KyaPayServerConfig",
    # Extension utilities
    "get_extension_declaration",
    "check_extension_activation",
    "add_extension_activation_header",
]
