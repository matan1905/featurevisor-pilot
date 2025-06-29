from flask import Blueprint, jsonify
from services.redis_service import redis_service

datafile_bp = Blueprint('datafile', __name__)


@datafile_bp.route('/datafile/<path:filename>')
def serve_datafile(filename):
    """Serve datafile from Redis."""
    datafile = redis_service.get_datafile(filename)

    if datafile:
        return jsonify(datafile)
    else:
        return jsonify({"error": "Datafile not found"}), 404