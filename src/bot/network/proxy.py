from .models import Proxy


class ProxyManager:

    def __init__(self, proxies=None):

        self.proxies = []

        if proxies:

            for p in proxies:

                self.add(p)

    def add(self, proxy):

        self.proxies.append(Proxy(url=proxy))

    def get(self):

        for proxy in self.proxies:

            if proxy.alive:

                return proxy.url

        return None

    def fail(self, proxy_url):

        for proxy in self.proxies:

            if proxy.url == proxy_url:

                proxy.failures += 1

                if proxy.failures >= 5:

                    proxy.alive = False

    def success(self, proxy_url):

        for proxy in self.proxies:

            if proxy.url == proxy_url:

                proxy.success += 1

                proxy.failures = 0
