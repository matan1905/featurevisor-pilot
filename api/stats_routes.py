from flask import Blueprint, request, jsonify
import threading
import logging

from services.redis_service import redis_service
from services.experiment_service import ExperimentService

stats_bp = Blueprint('stats', __name__)
logger = logging.getLogger(__name__)


@stats_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get statistics for all features."""
    try:
        datafile = request.args.get('datafile')
        feature = request.args.get('feature')

        if datafile and feature:
            # Get specific feature stats
            variants = redis_service.get_all_variants_for_feature(datafile, feature)
            results = {datafile: {feature: []}}

            for variant in variants:
                conversion_rate = 0
                if variant['exposures'] > 0:
                    conversion_rate = (variant['conversions'] / variant['exposures']) * 100

                results[datafile][feature].append({
                    'variant': variant['variant'],
                    'exposures': variant['exposures'],
                    'conversions': variant['conversions'],
                    'conversion_rate': round(conversion_rate, 2),
                    'weight': round(variant['weight'], 2),
                    'last_updated': variant['last_updated']
                })
        else:
            # Get all stats
            all_stats = redis_service.get_all_features_stats(datafile)
            results = {}

            for df_key, features in all_stats.items():
                results[df_key] = {}
                for feat_key, variants in features.items():
                    results[df_key][feat_key] = []

                    for variant in variants:
                        conversion_rate = 0
                        if variant['exposures'] > 0:
                            conversion_rate = (variant['conversions'] / variant['exposures']) * 100

                        results[df_key][feat_key].append({
                            'variant': variant['variant'],
                            'exposures': variant['exposures'],
                            'conversions': variant['conversions'],
                            'conversion_rate': round(conversion_rate, 2),
                            'weight': round(variant['weight'], 2),
                            'last_updated': variant['last_updated']
                        })

        return jsonify(results), 200

    except Exception as e:
        logger.error(f"Error in /stats: {e}")
        return jsonify({"error": str(e)}), 500


@stats_bp.route('/recalculate', methods=['POST'])
def trigger_recalculation():
    """Manually trigger weight recalculation."""
    try:
        thread = threading.Thread(
            target=ExperimentService.calculate_thompson_sampling_weights
        )
        thread.start()

        return jsonify({
            "status": "success",
            "message": "Weight recalculation triggered"
        }), 200

    except Exception as e:
        logger.error(f"Error in /recalculate: {e}")
        return jsonify({"error": str(e)}), 500