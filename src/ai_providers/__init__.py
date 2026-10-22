"""Provider-specific request and streaming implementations for AIClient.

Each module receives the client as its first argument, so the shared transport
(`_make_request`), retry policy, usage accounting and stream limits stay in one
place. The client keeps thin methods with the historical private names, which
also preserves the plugin contract (`_chat_<name>` / `_stream_<name>`).
"""

import logging


logger = logging.getLogger("src.ai_client")
