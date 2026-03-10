import time
import functools
from typing import Callable, Type, Tuple
from loguru import logger


def with_retry(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    no_retry_on: Tuple[Type[Exception], ...] = (),
):
    """
    Decorator for retry with exponential backoff.
    Retries on specified exceptions, skips retry on no_retry_on exceptions.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except no_retry_on as e:
                    raise
                except retry_on as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = backoff_base * (2 ** attempt)
                        logger.warning(
                            f"[retry] {func.__name__} attempt {attempt+1}/{max_retries} failed: {e}. "
                            f"Retrying in {wait:.1f}s..."
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            f"[retry] {func.__name__} failed after {max_retries} retries: {e}"
                        )
            raise last_exc
        return wrapper
    return decorator


def retry_request(func: Callable) -> Callable:
    """
    Convenience decorator for HTTP requests.
    Retries on connection errors, 429, 5xx.
    Does not retry on 400, 401, 403, 404.
    """
    import requests

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                response = func(*args, **kwargs)
                # Handle HTTP error status codes
                if hasattr(response, 'status_code'):
                    if response.status_code in (400, 401, 403, 404):
                        return response  # Don't retry client errors
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < max_retries:
                            wait = 1.0 * (2 ** attempt)
                            logger.warning(
                                f"[retry] HTTP {response.status_code} on {func.__name__}, "
                                f"retrying in {wait:.1f}s..."
                            )
                            time.sleep(wait)
                            continue
                return response
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < max_retries:
                    wait = 1.0 * (2 ** attempt)
                    logger.warning(
                        f"[retry] {func.__name__} connection error: {e}. Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"[retry] {func.__name__} failed after {max_retries} retries: {e}")
                    raise
        if last_exc:
            raise last_exc
    return wrapper
