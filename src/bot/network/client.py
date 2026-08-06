import asyncio

import aiohttp

from .logger import NetLogger
from .models import RequestResult
from .recovery import RecoveryPipeline
from .retry import RetryPolicy


class RequestClient:

    def __init__(self, session_manager, recovery=None):

        self.session = session_manager

        self.retry = RetryPolicy()

        self.recovery = recovery

        self.stats_data = {"requests": 0, "success": 0, "failed": 0, "rate_limit": 0}

    async def request(self, method, url, **kwargs):

        for attempt in range(self.retry.attempts):

            self.stats_data["requests"] += 1

            try:

                async with await self.session.request(
                    method, url, **kwargs
                ) as response:

                    status = response.status

                    # ======================
                    # SUCCESS
                    # ======================

                    if status == 200:

                        self.stats_data["success"] += 1

                        try:

                            data = await response.json()

                        except Exception:

                            data = {"text": await response.text()}

                        return RequestResult(success=True, status=status, data=data)

                    # ======================
                    # RATE LIMIT
                    # ======================

                    elif status == 429:

                        self.stats_data["rate_limit"] += 1

                        NetLogger.warning("429 Too Many Requests")

                        if self.recovery:

                            await self.recovery.recover(attempt)

                        else:

                            await self.retry.wait(attempt)

                        continue

                    # ======================
                    # SERVER ERROR
                    # ======================

                    elif status >= 500:

                        NetLogger.warning(f"Server error {status}")

                        await self.retry.wait(attempt)

                        continue

                    # ======================
                    # CLIENT ERROR
                    # ======================

                    else:

                        body = await response.text()

                        self.stats_data["failed"] += 1

                        return RequestResult(
                            success=False, status=status, error=body[:500]
                        )

            except aiohttp.ClientError as e:

                self.stats_data["failed"] += 1

                NetLogger.error(f"Network error {e}")

                await self.retry.wait(attempt)

            except asyncio.TimeoutError:

                self.stats_data["failed"] += 1

                NetLogger.warning("Request timeout")

                await self.retry.wait(attempt)

            except Exception as e:

                self.stats_data["failed"] += 1

                NetLogger.error(str(e))

                await self.retry.wait(attempt)

        return RequestResult(success=False, status=0, error="Maximum retries exceeded")

    async def get(self, url, params=None, headers=None):

        return await self.request("GET", url, params=params, headers=headers)

    async def post(self, url, json=None, headers=None):

        return await self.request("POST", url, json=json, headers=headers)

    def stats(self):

        return self.stats_data
