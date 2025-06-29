import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Redis Configuration
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

    # Application Configuration
    DATAFILES_DIR = os.getenv('DATAFILES_DIR', '../dist')
    UPDATE_INTERVAL_MINUTES = int(os.getenv('UPDATE_INTERVAL_MINUTES', 30))
    MIN_EXPOSURES_FOR_UPDATE = int(os.getenv('MIN_EXPOSURES_FOR_UPDATE', 10))

    # Flask Configuration
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5050))
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

    # Redis Key Prefixes
    REDIS_PREFIX_DATAFILE = 'datafile:'
    REDIS_PREFIX_STATS = 'stats:'
    REDIS_PREFIX_HISTORY = 'history:'
    REDIS_PREFIX_LOCK = 'lock:'

    # Redis TTLs (in seconds)
    DATAFILE_TTL = 3600  # 1 hour
    STATS_TTL = None  # No expiration for stats