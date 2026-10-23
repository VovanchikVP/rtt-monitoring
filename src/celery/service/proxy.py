import asyncio
import random

import aiohttp


class ProxyService:
    URL = (
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt"
    )
    TEST_URL = "http://httpbin.org/ip"
    MAX_RETRIES = 10
    TIME_SLIP = 15

    def __init__(self):
        self.proxies = []
        self.run_creating_pool = None

    @property
    def need_create_pool(self) -> bool:
        return self.run_creating_pool is None and not self.proxies

    async def create_pool(self):
        """Формирование рабочего пула proxies"""
        async with aiohttp.ClientSession() as s:
            text = await (await s.get(self.URL)).text()
            proxies = [p if "://" in p else f"http://{p}" for p in text.split()]
            sem = asyncio.Semaphore(100)
            await asyncio.gather(*(self._add_proxy_in_pool(s, p, sem) for p in proxies))
        await self.run_creating_pool
        self.run_creating_pool = None

    async def get(self, retry: int = 0):
        """Получение прокси из пула"""
        if retry == self.MAX_RETRIES:
            raise TimeoutError(
                f"Время получения прокси превысило {self.MAX_RETRIES * self.TIME_SLIP} сек."
            )

        if self.need_create_pool:
            self.run_creating_pool = asyncio.create_task(self.create_pool())

        async with aiohttp.ClientSession() as s:
            if self.proxies:
                proxy = random.choice(self.proxies)
                if proxy := await self._check(s, proxy):
                    return proxy
                else:
                    self.proxies.remove(proxy)
                    if self.need_create_pool:
                        self.run_creating_pool = asyncio.create_task(self.create_pool())

        await asyncio.sleep(self.TIME_SLIP)
        return await self.get(retry + 1)

    async def _add_proxy_in_pool(self, session, proxy, sem):
        async with sem:
            if proxy := await self._check(session, proxy):
                self.proxies.append(proxy)

    async def _check(self, session, proxy):
        try:
            async with session.get(
                self.TEST_URL, proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    return proxy
        except Exception:
            pass


proxy_service = ProxyService()
