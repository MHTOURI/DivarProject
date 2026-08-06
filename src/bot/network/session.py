import aiohttp

from .logger import NetLogger


class SessionManager:

    def __init__(self, timeout=35):

        self.session = None

        self.proxy = None

        self.timeout = timeout

        self.headers = {
            "Accept": "application/json",
            "Accept-Language": "fa-IR,fa;q=0.9",
            "Connection": "keep-alive",
        }

    async def start(self):

        if self.session:

            return self.session

        self.session = aiohttp.ClientSession(
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            connector=aiohttp.TCPConnector(limit=50, ttl_dns_cache=300),
        )

        NetLogger.success("HTTP Session Started")

        return self.session

    async def request(self, method, url, **kwargs):

        session = await self.start()

        if self.proxy:

            kwargs["proxy"] = self.proxy

        return session.request(method, url, **kwargs)

    async def refresh(self):

        NetLogger.warning("Refreshing session")

        await self.close()

        return await self.start()

    async def close(self):

        if self.session:

            await self.session.close()

            self.session = None

            NetLogger.info("Session Closed")
