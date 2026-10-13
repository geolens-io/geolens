"""Wire protocol for every redis-py client GeoLens builds from ``REDIS_URL``."""

# redis-py 8 opens each connection with HELLO 3 and does not fall back, so a
# server or proxy without HELLO (Redis before 6, some managed proxies) would
# refuse every connection. RESP2 works against all of them, and the RESP2
# response shapes are what the callers parse.
REDIS_PROTOCOL = 2
