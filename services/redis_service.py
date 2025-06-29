import redis
import json
import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import time

from config import Config

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            password=Config.REDIS_PASSWORD,
            decode_responses=True
        )
        self._test_connection()

    def _test_connection(self):
        """Test Redis connection on initialization."""
        try:
            self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    @contextmanager
    def lock(self, key: str, timeout: int = 10):
        """Distributed lock using Redis."""
        lock_key = f"{Config.REDIS_PREFIX_LOCK}{key}"
        identifier = str(time.time())

        try:
            # Try to acquire lock
            if self.redis_client.set(lock_key, identifier, nx=True, ex=timeout):
                yield
            else:
                raise Exception(f"Could not acquire lock for {key}")
        finally:
            # Release lock only if we own it
            current = self.redis_client.get(lock_key)
            if current == identifier:
                self.redis_client.delete(lock_key)

    # Datafile operations
    def get_datafile(self, path: str) -> Optional[Dict]:
        """Get datafile from Redis."""
        key = f"{Config.REDIS_PREFIX_DATAFILE}{path}"
        data = self.redis_client.get(key)
        return json.loads(data) if data else None

    def set_datafile(self, path: str, data: Dict, ttl: Optional[int] = Config.DATAFILE_TTL):
        """Store datafile in Redis."""
        key = f"{Config.REDIS_PREFIX_DATAFILE}{path}"
        self.redis_client.set(key, json.dumps(data), ex=ttl)

    def get_all_datafile_keys(self) -> List[str]:
        """Get all datafile keys."""
        pattern = f"{Config.REDIS_PREFIX_DATAFILE}*"
        keys = self.redis_client.keys(pattern)
        return [k.replace(Config.REDIS_PREFIX_DATAFILE, '') for k in keys]

    # Variant stats operations
    def increment_stat(self, datafile: str, feature: str, variant: str, stat_type: str):
        """Increment exposure or conversion count."""
        key = f"{Config.REDIS_PREFIX_STATS}{datafile}:{feature}:{variant}"
        field = stat_type  # 'exposures' or 'conversions'
        self.redis_client.hincrby(key, field, 1)
        self.redis_client.hset(key, 'last_updated', int(time.time()))

    def get_variant_stats(self, datafile: str, feature: str, variant: str) -> Dict:
        """Get stats for a specific variant."""
        key = f"{Config.REDIS_PREFIX_STATS}{datafile}:{feature}:{variant}"
        stats = self.redis_client.hgetall(key)

        # Convert to proper types
        return {
            'exposures': int(stats.get('exposures', 0)),
            'conversions': int(stats.get('conversions', 0)),
            'weight': float(stats.get('weight', 0.0)),
            'last_updated': int(stats.get('last_updated', 0))
        }

    def set_variant_weight(self, datafile: str, feature: str, variant: str, weight: float):
        """Update variant weight."""
        key = f"{Config.REDIS_PREFIX_STATS}{datafile}:{feature}:{variant}"
        self.redis_client.hset(key, 'weight', weight)
        self.redis_client.hset(key, 'last_updated', int(time.time()))

    def get_all_variants_for_feature(self, datafile: str, feature: str) -> List[Dict]:
        """Get all variants for a feature."""
        pattern = f"{Config.REDIS_PREFIX_STATS}{datafile}:{feature}:*"
        keys = self.redis_client.keys(pattern)

        variants = []
        for key in keys:
            variant = key.split(':')[-1]
            stats = self.get_variant_stats(datafile, feature, variant)
            stats['variant'] = variant
            variants.append(stats)

        return variants

    def get_all_features_stats(self, datafile: Optional[str] = None) -> Dict:
        """Get stats for all features, optionally filtered by datafile."""
        if datafile:
            pattern = f"{Config.REDIS_PREFIX_STATS}{datafile}:*"
        else:
            pattern = f"{Config.REDIS_PREFIX_STATS}*"

        keys = self.redis_client.keys(pattern)
        results = {}

        for key in keys:
            parts = key.replace(Config.REDIS_PREFIX_STATS, '').split(':')
            if len(parts) >= 3:
                df, feature, variant = parts[0], parts[1], parts[2]

                if df not in results:
                    results[df] = {}
                if feature not in results[df]:
                    results[df][feature] = []

                stats = self.redis_client.hgetall(key)
                results[df][feature].append({
                    'variant': variant,
                    'exposures': int(stats.get('exposures', 0)),
                    'conversions': int(stats.get('conversions', 0)),
                    'weight': float(stats.get('weight', 0.0)),
                    'last_updated': int(stats.get('last_updated', 0))
                })

        return results

    def add_weight_history(self, datafile: str, feature: str, variant: str,
                           weight: float, prob_being_best: float):
        """Add weight calculation to history."""
        key = f"{Config.REDIS_PREFIX_HISTORY}{datafile}:{feature}"
        timestamp = int(time.time())

        history_entry = {
            'variant': variant,
            'weight': weight,
            'prob_being_best': prob_being_best,
            'timestamp': timestamp
        }

        # Add to sorted set with timestamp as score
        self.redis_client.zadd(key, {json.dumps(history_entry): timestamp})

        # Keep only last 1000 entries
        self.redis_client.zremrangebyrank(key, 0, -1001)


# Singleton instance
redis_service = RedisService()