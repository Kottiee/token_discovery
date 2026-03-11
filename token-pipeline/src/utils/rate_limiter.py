import threading
import time


class RateLimiter:
    def __init__(self, rate_limit: int, period: int = 60):
        """
        Token bucket rate limiter.
        :param rate_limit: Number of requests allowed per period
        :param period: Period in seconds
        """
        self.rate_limit = rate_limit
        self.period = period
        self.tokens = rate_limit
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            # Refill tokens
            elapsed = now - self.last_refill
            refill_amount = elapsed * (self.rate_limit / self.period)
            self.tokens = min(self.rate_limit, self.tokens + refill_amount)
            self.last_refill = now

            if self.tokens < 1:
                sleep_time = (1 - self.tokens) * (self.period / self.rate_limit)
                time.sleep(sleep_time)
                self.tokens = 0
                self.last_refill = time.time()
            else:
                self.tokens -= 1
