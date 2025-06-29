import logging
from typing import Dict, List
from bayesian_testing.experiments import BinaryDataTest

from config import Config
from services.redis_service import redis_service
from services.datafile_service import DatafileService

logger = logging.getLogger(__name__)


class ExperimentService:
    @staticmethod
    def calculate_thompson_sampling_weights():
        """Calculate Thompson sampling weights based on conversion data."""
        logger.info("Starting Thompson sampling weight calculation...")

        # Get all features with sufficient data
        all_stats = redis_service.get_all_features_stats()

        for datafile_path, features in all_stats.items():
            for feature_key, variants in features.items():
                # Filter variants with minimum exposures
                eligible_variants = [
                    v for v in variants
                    if v['exposures'] >= Config.MIN_EXPOSURES_FOR_UPDATE
                ]

                if len(eligible_variants) < 2 or len(eligible_variants) != len(variants):
                    continue

                try:
                    # Initialize Bayesian test
                    test = BinaryDataTest()
                    variant_names = []

                    for variant in eligible_variants:
                        if variant['exposures'] > 0:
                            variant_names.append(variant['variant'])
                            test.add_variant_data_agg(
                                variant['variant'],
                                totals=variant['exposures'],
                                positives=variant['conversions']
                            )

                    if len(variant_names) < 2:
                        continue

                    # Calculate probabilities
                    results = test.evaluate()

                    # Extract probabilities and calculate weights
                    prob_being_best = {}
                    for result in results:
                        prob_being_best[result['variant']] = result['prob_being_best']

                    # Convert probabilities to weights
                    raw_weights = {k: v * 100 for k, v in prob_being_best.items()}

                    normalized_weights = DatafileService.normalize_weights(raw_weights)

                    # Update weights and log history
                    for variant_name, weight in normalized_weights.items():
                        redis_service.set_variant_weight(
                            datafile_path, feature_key, variant_name, weight
                        )

                        redis_service.add_weight_history(
                            datafile_path, feature_key, variant_name,
                            weight, prob_being_best[variant_name]
                        )

                    # Update datafile weights
                    DatafileService.update_datafile_weights(
                        datafile_path, feature_key, normalized_weights
                    )

                    logger.info(
                        f"Updated weights for {datafile_path}/{feature_key}: "
                        f"{normalized_weights}"
                    )

                except Exception as e:
                    logger.error(
                        f"Error calculating weights for "
                        f"{datafile_path}/{feature_key}: {e}"
                    )

