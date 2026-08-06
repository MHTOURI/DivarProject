import random


class UserAgentPool:

    def __init__(self):

        self.agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Mozilla/5.0 (X11; Linux x86_64)",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X)",
        ]

        self.index = 0

    def get(self):

        return random.choice(self.agents)

    def next(self):

        ua = self.agents[self.index % len(self.agents)]

        self.index += 1

        return ua
