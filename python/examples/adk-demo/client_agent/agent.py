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
import os
import httpx

# Local imports
from client_agent._task_store import TaskStore
from client_agent.client_agent import ClientAgent

# Default to localhost for local development
default_merchant_url = "http://localhost:10000/agents/merchant_agent"
merchant_url = os.getenv("MERCHANT_AGENT_URL", default_merchant_url)

root_agent = ClientAgent(
    remote_agent_addresses=[
        merchant_url,
    ],
    http_client=httpx.AsyncClient(timeout=30),
    # wallet=MockLocalWallet(),
    task_callback=TaskStore().update_task,
).create_agent()
