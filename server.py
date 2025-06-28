import os
import json
import sqlite3
import glob
import threading
import time
from pathlib import Path
from typing import Dict, List, Any, Tuple
from contextlib import contextmanager
from datetime import datetime
import logging

from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from bayesian_testing.experiments import BinaryDataTest
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
DB_PATH = './db/sqlite.db'
DATAFILES_DIR = './definitions/dist'
UPDATE_INTERVAL_MINUTES = 30
MIN_EXPOSURES_FOR_UPDATE = 10

# Thread-safe in-memory datafiles storage
datafiles_lock = threading.RLock()
datafiles_cache: Dict[str, Dict] = {}


# Database operations
@contextmanager
def get_db():
    """Thread-safe database connection context manager."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS variant_stats (
                datafile TEXT NOT NULL,
                feature TEXT NOT NULL,
                variant TEXT NOT NULL,
                exposures INTEGER DEFAULT 0,
                conversions INTEGER DEFAULT 0,
                weight REAL DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (datafile, feature, variant)
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS weights_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datafile TEXT NOT NULL,
                feature TEXT NOT NULL,
                variant TEXT NOT NULL,
                weight REAL NOT NULL,
                prob_being_best REAL NOT NULL,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create indexes
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_variant_stats_datafile_feature ON variant_stats(datafile, feature)')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_weights_history_lookup ON weights_history(datafile, feature, calculated_at)')


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


def extract_variations_from_datafile(datafile_data: Dict) -> Dict[str, List[Dict]]:
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


def load_datafiles_to_memory():
    """Load all datafiles from disk to memory and sync with database."""
    logger.info("Loading datafiles to memory...")

    pattern = os.path.join(DATAFILES_DIR, '**', '*.json')
    json_files = glob.glob(pattern, recursive=True)

    with datafiles_lock:
        datafiles_cache.clear()

        for file_path in json_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Calculate relative path for URL mapping
                relative_path = os.path.relpath(file_path, DATAFILES_DIR)
                datafiles_cache[relative_path] = data

                # Process variations
                variations = extract_variations_from_datafile(data)
                if variations:
                    sync_variations_with_db(relative_path, variations, data)

            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")

    logger.info(f"Loaded {len(datafiles_cache)} datafiles to memory")


def sync_variations_with_db(datafile_path: str, variations: Dict[str, List[Dict]], datafile_data: Dict):
    """Sync variations with database and update weights in memory."""
    with get_db() as conn:
        for feature_key, feature_variations in variations.items():
            # Get existing weights from database
            db_weights = {}
            rows = conn.execute(
                'SELECT variant, weight FROM variant_stats WHERE datafile = ? AND feature = ?',
                (datafile_path, feature_key)
            ).fetchall()

            for row in rows:
                db_weights[row['variant']] = row['weight']

            # Update or insert variants
            variant_weights = {}
            for variation in feature_variations:
                variant_value = variation['value']

                if variant_value in db_weights:
                    # Use weight from database
                    variant_weights[variant_value] = db_weights[variant_value]
                else:
                    # Insert new variant with original weight
                    original_weight = variation['weight']
                    conn.execute('''
                        INSERT INTO variant_stats (datafile, feature, variant, weight)
                        VALUES (?, ?, ?, ?)
                    ''', (datafile_path, feature_key, variant_value, original_weight))
                    variant_weights[variant_value] = original_weight

            # Normalize weights
            normalized_weights = normalize_weights(variant_weights)

            # Update weights in memory
            update_datafile_weights_in_memory(datafile_path, feature_key, normalized_weights)


def update_datafile_weights_in_memory(datafile_path: str, feature_key: str, weights: Dict[str, float]):
    """Update variation weights in the in-memory datafile."""
    with datafiles_lock:
        if datafile_path in datafiles_cache:
            datafile = datafiles_cache[datafile_path]
            if 'features' in datafile and feature_key in datafile['features']:
                feature = datafile['features'][feature_key]
                if 'variations' in feature:
                    for variation in feature['variations']:
                        variant_value = variation['value']
                        if variant_value in weights:
                            variation['weight'] = weights[variant_value]


def calculate_thompson_sampling_weights():
    """Calculate Thompson sampling weights based on conversion data."""
    logger.info("Starting Thompson sampling weight calculation...")

    with get_db() as conn:
        # Get all unique datafile/feature combinations
        combos = conn.execute('''
            SELECT DISTINCT datafile, feature 
            FROM variant_stats 
            WHERE exposures >= ?
        ''', (MIN_EXPOSURES_FOR_UPDATE,)).fetchall()

        for combo in combos:
            datafile_path = combo['datafile']
            feature_key = combo['feature']

            # Get variants for this feature
            variants = conn.execute('''
                SELECT variant, exposures, conversions 
                FROM variant_stats 
                WHERE datafile = ? AND feature = ?
            ''', (datafile_path, feature_key)).fetchall()

            if len(variants) < 2:
                continue

            try:
                # Initialize Bayesian test
                test = BinaryDataTest()
                variant_names = []

                for variant in variants:
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
                normalized_weights = normalize_weights(raw_weights)

                # Update database
                for variant_name, weight in normalized_weights.items():
                    conn.execute('''
                        UPDATE variant_stats 
                        SET weight = ?, last_updated = CURRENT_TIMESTAMP 
                        WHERE datafile = ? AND feature = ? AND variant = ?
                    ''', (weight, datafile_path, feature_key, variant_name))

                    # Log history
                    conn.execute('''
                        INSERT INTO weights_history (datafile, feature, variant, weight, prob_being_best)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (datafile_path, feature_key, variant_name, weight, prob_being_best[variant_name]))

                # Update in-memory datafile
                update_datafile_weights_in_memory(datafile_path, feature_key, normalized_weights)

                logger.info(f"Updated weights for {datafile_path}/{feature_key}: {normalized_weights}")

            except Exception as e:
                logger.error(f"Error calculating weights for {datafile_path}/{feature_key}: {e}")


# API Endpoints
@app.route('/datafile/<path:filename>')
def serve_datafile(filename):
    """Serve datafile from memory."""
    with datafiles_lock:
        if filename in datafiles_cache:
            return jsonify(datafiles_cache[filename])
        else:
            return jsonify({"error": "Datafile not found"}), 404


@app.route('/expose', methods=['POST'])
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

        with get_db() as conn:
            for feature, variant in features.items():
                conn.execute('''
                    UPDATE variant_stats 
                    SET exposures = exposures + 1, last_updated = CURRENT_TIMESTAMP
                    WHERE datafile = ? AND feature = ? AND variant = ?
                ''', (datafile_path, feature, variant))

        return jsonify({
            "status": "success",
            "message": "Exposures recorded",
            "features": list(features.keys())
        }), 200

    except Exception as e:
        logger.error(f"Error in /expose: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/convert', methods=['POST'])
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

        with get_db() as conn:
            for feature, variant in features.items():
                conn.execute('''
                    UPDATE variant_stats 
                    SET conversions = conversions + 1, last_updated = CURRENT_TIMESTAMP
                    WHERE datafile = ? AND feature = ? AND variant = ?
                ''', (datafile_path, feature, variant))

        return jsonify({
            "status": "success",
            "message": "Conversions recorded",
            "features": list(features.keys())
        }), 200

    except Exception as e:
        logger.error(f"Error in /convert: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get statistics for all features."""
    try:
        datafile = request.args.get('datafile')
        feature = request.args.get('feature')

        query = '''
            SELECT datafile, feature, variant, exposures, conversions, weight,
                   CASE WHEN exposures > 0 
                        THEN CAST(conversions AS FLOAT) / exposures * 100
                        ELSE 0 
                   END as conversion_rate,
                   last_updated
            FROM variant_stats
        '''
        params = []

        if datafile:
            query += ' WHERE datafile = ?'
            params.append(datafile)
            if feature:
                query += ' AND feature = ?'
                params.append(feature)
        elif feature:
            query += ' WHERE feature = ?'
            params.append(feature)

        query += ' ORDER BY datafile, feature, variant'

        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()

        # Organize results
        results = {}
        for row in rows:
            df_key = row['datafile']
            if df_key not in results:
                results[df_key] = {}

            feat_key = row['feature']
            if feat_key not in results[df_key]:
                results[df_key][feat_key] = []

            results[df_key][feat_key].append({
                'variant': row['variant'],
                'exposures': row['exposures'],
                'conversions': row['conversions'],
                'conversion_rate': round(row['conversion_rate'], 2),
                'weight': round(row['weight'], 2),
                'last_updated': row['last_updated']
            })

        return jsonify(results), 200

    except Exception as e:
        logger.error(f"Error in /stats: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/recalculate', methods=['POST'])
def trigger_recalculation():
    """Manually trigger weight recalculation."""
    try:
        thread = threading.Thread(target=calculate_thompson_sampling_weights)
        thread.start()
        return jsonify({
            "status": "success",
            "message": "Weight recalculation triggered"
        }), 200
    except Exception as e:
        logger.error(f"Error in /recalculate: {e}")
        return jsonify({"error": str(e)}), 500


def run_scheduler():
    """Initialize and run the scheduler."""
    scheduler = BackgroundScheduler()

    # Schedule periodic weight calculations
    scheduler.add_job(
        func=calculate_thompson_sampling_weights,
        trigger="interval",
        minutes=UPDATE_INTERVAL_MINUTES,
        id='thompson_sampling_calc',
        name='Calculate Thompson Sampling Weights',
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"Scheduler started - will update weights every {UPDATE_INTERVAL_MINUTES} minutes")


if __name__ == '__main__':
    # Initialize database
    init_db()

    # Load datafiles to memory
    load_datafiles_to_memory()

    # Start scheduler
    run_scheduler()

    # Run Flask app
    app.run(host='0.0.0.0', port=5050, debug=False)
