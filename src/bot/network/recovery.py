import asyncio
import random

from .logger import NetLogger


class RecoveryPipeline:

    def __init__(self, session, ua_pool, cookie_manager, proxy_manager):

        self.session = session

        self.ua_pool = ua_pool

        self.cookie_manager = cookie_manager

        self.proxy_manager = proxy_manager

    async def recover(self, attempt):

        NetLogger.warning("429 Recovery Started")

        await self.change_user_agent()

        await self.change_cookie()

        if attempt >= 2:

            await self.change_proxy()

        await self.session.refresh()

        delay = random.uniform(3, 10)

        NetLogger.info(f"Recovery delay {delay:.2f}s")

        await asyncio.sleep(delay)

    async def change_user_agent(self):

        ua = self.ua_pool.next()

        self.session.headers["User-Agent"] = ua

        NetLogger.info("User-Agent changed")

    async def change_cookie(self):

        cookie = self.cookie_manager.get()

        if cookie:

            value = "; ".join([f"{k}={v}" for k, v in cookie.items()])

            self.session.headers["Cookie"] = value

        NetLogger.info("Cookie changed")

    async def change_proxy(self):

        proxy = self.proxy_manager.get()

        if proxy:

            self.session.proxy = proxy

            NetLogger.warning(f"Proxy changed")
