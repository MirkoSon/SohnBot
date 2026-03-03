"""Entry point for `python -m sohnbot`."""

import asyncio

from sohnbot.config.manager import initialize_config
from sohnbot.main import run_main

initialize_config()
asyncio.run(run_main())
