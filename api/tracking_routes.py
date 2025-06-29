from flask import Blueprint, request, jsonify
import logging

from services.redis_service import redis_service

tracking_bp = Blueprint('tracking', __name__)
logger = logging.getLogger(__name__)


@tracking_bp.route('/expose', methods=['POST'])
def expose():
    """
    Track exposures for features.
    Expected format:
    {
        "datafile": "path/to/datafile.json",
        "features": {
            "feature1": "variant1",
            "feature2": "variant2"
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'datafile' not in data or 'features' not in data:
            return jsonify({"error": "Invalid request format"}), 400

        datafile_path = data['datafile']
        features = data['features']

        for feature, variant in features.items():
            redis_service.increment_stat(datafile_path, feature, variant, 'exposures')

        return jsonify({
            "status": "success",
            "message": "Exposures recorded",
            "features": list(features.keys())
        }), 200

    except Exception as e:
        logger.error(f"Error in /expose: {e}")
        return jsonify({"error": str(e)}), 500


@tracking_bp.route('/convert', methods=['POST'])
def convert():
    """
    Track conversions for features.
    Same format as /expose endpoint.
    """
    try:
        data = request.get_json()
        if not data or 'datafile' not in data or 'features' not in data:
            return jsonify({"error": "Invalid request format"}), 400

        datafile_path = data['datafile']
        features = data['features']

        for feature, variant in features.items():
            redis_service.increment_stat(datafile_path, feature, variant, 'conversions')

        return jsonify({
            "status": "success",
            "message": "Conversions recorded",
            "features": list(features.keys())
        }), 200

    except Exception as e:
        logger.error(f"Error in /convert: {e}")
        return jsonify({"error": str(e)}), 500