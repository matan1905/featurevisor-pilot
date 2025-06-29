import os
import json
import glob
import logging
from typing import Dict, List

from config import Config
from services.redis_service import redis_service

logger = logging.getLogger(__name__)


class DatafileService:
    @staticmethod
    def extract_variations_from_datafile(datafile_data):
        """Extract variations from a datafile."""
        variations = {}
        features = datafile_data.get('features', {})

        for feature_key, feature_data in features.items():
            feature_variations = feature_data.get('variations', [])
            if feature_variations:
                variations[feature_key] = [
                    {
                        'value': v['value'],
                        'weight': v.get('weight', 0)
                    }
                    for v in feature_variations
                ]

        return variations

    @staticmethod
    def load_datafiles_to_redis():
        """Load all datafiles from disk to Redis."""
        logger.info("Loading datafiles to Redis from " + Config.DATAFILES_DIR)
        pattern = os.path.join(Config.DATAFILES_DIR, '**', '*.json')
        json_files = glob.glob(pattern, recursive=True)

        loaded_count = 0
        for file_path in json_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Calculate relative path
                relative_path = os.path.relpath(file_path, Config.DATAFILES_DIR)

                # Store in Redis
                redis_service.set_datafile(relative_path, data)

                # Process variations
                variations = DatafileService.extract_variations_from_datafile(data)
                if variations:
                    DatafileService.sync_variations_with_redis(relative_path, variations, data)

                loaded_count += 1

            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")

        logger.info(f"Loaded {loaded_count} datafiles to Redis")

    @staticmethod
    def sync_variations_with_redis(datafile_path: str, variations: Dict[str, List[Dict]],
                                   datafile_data: Dict):
        """Sync variations with Redis and update weights."""
        for feature_key, feature_variations in variations.items():
            variant_weights = {}

            for variation in feature_variations:
                variant_value = variation['value']

                # Get existing stats
                stats = redis_service.get_variant_stats(
                    datafile_path, feature_key, variant_value
                )

                if stats['weight'] > 0:
                    # Use existing weight
                    variant_weights[variant_value] = stats['weight']
                else:
                    # Use original weight and initialize stats
                    original_weight = variation['weight']
                    variant_weights[variant_value] = original_weight
                    redis_service.set_variant_weight(
                        datafile_path, feature_key, variant_value, original_weight
                    )

            # Normalize weights
            normalized_weights = DatafileService.normalize_weights(variant_weights)

            # Update weights in Redis and datafile
            DatafileService.update_datafile_weights(
                datafile_path, feature_key, normalized_weights
            )

    @staticmethod
    def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize weights to sum to 100 with max 2 decimal places."""
        total = sum(weights.values())
        if total == 0:
            # Equal distribution if no weights
            equal_weight = 100.0 / len(weights)
            return {k: round(equal_weight, 2) for k in weights}

        # Normalize to 100
        normalized = {k: (v / total) * 100 for k, v in weights.items()}

        # Round to 2 decimal places
        rounded = {k: round(v, 2) for k, v in normalized.items()}

        # Adjust for rounding errors
        diff = 100.0 - sum(rounded.values())
        if diff != 0:
            # Add difference to the largest weight
            max_key = max(rounded, key=rounded.get)
            rounded[max_key] += diff
            rounded[max_key] = round(rounded[max_key], 2)

        return rounded

    @staticmethod
    def update_datafile_weights(datafile_path: str, feature_key: str,
                                weights: Dict[str, float]):
        """Update variation weights in the datafile stored in Redis."""
        datafile = redis_service.get_datafile(datafile_path)
        if not datafile:
            return

        if 'features' in datafile and feature_key in datafile['features']:
            feature = datafile['features'][feature_key]
            if 'variations' in feature:
                for variation in feature['variations']:
                    variant_value = variation['value']
                    if variant_value in weights:
                        variation['weight'] = weights[variant_value]

        # Update in Redis
        redis_service.set_datafile(datafile_path, datafile)

        # Update individual variant weights
        for variant, weight in weights.items():
            redis_service.set_variant_weight(datafile_path, feature_key, variant, weight)

