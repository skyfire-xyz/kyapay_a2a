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
"""Configuration types for kyapay_a2a."""

from typing import Optional
from pydantic import BaseModel


KYAPAY_EXTENSION_URI = "https://github.com/skyfire-xyz/a2a-kyapay/tree/main/spec/v0.1"


class KyaPayExtensionConfig(BaseModel):
    """Configuration for kyapay extension."""
    extension_uri: str = KYAPAY_EXTENSION_URI
    version: str = "0.1"
    skyfire_version: int = 1
    required: bool = True


class KyaPayServerConfig(BaseModel):
    """Configuration for how a server expects to be paid."""
    price: str
    seller_service_id: str  # Changed from pay_to_seller_service_id
    description: str = "Skyfire payment required..."
    mime_type: str = "application/json"
    max_timeout_seconds: int = 600
    resource: Optional[str] = None
