import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from services.datafile_service import DatafileService
from services.experiment_service import ExperimentService
from api.datafile_routes import datafile_bp
from api.tracking_routes import tracking_bp
from api.stats_routes import stats_bp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Register blueprints
app.register_blueprint(datafile_bp)
app.register_blueprint(tracking_bp)
app.register_blueprint(stats_bp)


def run_scheduler():
    """Initialize and run the scheduler."""
    scheduler = BackgroundScheduler()

    # Schedule periodic weight calculations
    scheduler.add_job(
        func=ExperimentService.calculate_thompson_sampling_weights,
        trigger="interval",
        minutes=Config.UPDATE_INTERVAL_MINUTES,
        id='thompson_sampling_calc',
        name='Calculate Thompson Sampling Weights',
        replace_existing=True
    )

    scheduler.start()
    logger.info(
        f"Scheduler started - will update weights every "
        f"{Config.UPDATE_INTERVAL_MINUTES} minutes"
    )


if __name__ == '__main__':
    # Load datafiles to Redis
    DatafileService.load_datafiles_to_redis()

    # Start scheduler
    run_scheduler()

    # Run Flask app
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)