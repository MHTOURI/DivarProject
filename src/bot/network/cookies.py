import random


class CookieManager:

    def __init__(self):

        self.cookies = []

        self.index = 0

    def add(self, cookie):

        self.cookies.append(cookie)

    def get(self):

        if not self.cookies:

            return {}

        cookie = self.cookies[self.index % len(self.cookies)]

        self.index += 1

        return cookie

    def random(self):

        if not self.cookies:

            return {}

        return random.choice(self.cookies)
