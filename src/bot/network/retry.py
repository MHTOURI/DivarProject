import asyncio
import random

from .logger import NetLogger


class RetryPolicy:

    def __init__(self, attempts=5, base_delay=2):

        self.attempts = attempts

        self.base_delay = base_delay

    async def wait(self, attempt):

        delay = self.base_delay * (2**attempt)

        delay *= random.uniform(0.5, 1.5)

        NetLogger.warning(f"Retry sleep {delay:.2f}s")

        await asyncio.sleep(delay)
