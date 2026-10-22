# Profile Cache

## Reads
Profile reads are served from an in-memory cache. A cache miss loads the profile from the database and stores it in the cache.

## Expiry
Every cached profile expires 10 minutes after it was stored.

## Capacity
The cache holds at most 50,000 profiles. When full, the least recently used profile is evicted.

## Warmup
After a restart the cache starts empty and fills as profiles are requested.
