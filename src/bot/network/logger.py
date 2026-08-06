from datetime import datetime


class NetLogger:

    @staticmethod
    def _time():

        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def info(msg):

        print(f"[{NetLogger._time()}] [INFO] {msg}")

    @staticmethod
    def warning(msg):

        print(f"[{NetLogger._time()}] [WARN] {msg}")

    @staticmethod
    def error(msg):

        print(f"[{NetLogger._time()}] [ERROR] {msg}")

    @staticmethod
    def success(msg):

        print(f"[{NetLogger._time()}] [OK] {msg}")
