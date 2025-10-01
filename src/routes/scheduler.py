from flask import Blueprint, jsonify
from src.services.scheduler import start_scheduler, stop_scheduler, is_scheduler_running
import logging

logger = logging.getLogger("scheduler_routes")

scheduler_bp = Blueprint('scheduler', __name__)

@scheduler_bp.route('/scheduler/start', methods=['POST'])
def start_scheduled_fetching():
    """
    Start the hourly signal fetching scheduler.
    """
    try:
        if is_scheduler_running():
            return jsonify({
                'success': False,
                'message': 'Scheduler is already running'
            }), 400
        
        start_scheduler()
        
        return jsonify({
            'success': True,
            'message': 'Hourly signal fetching scheduler started successfully'
        })
        
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        return jsonify({
            'success': False,
            'message': f'Error starting scheduler: {str(e)}'
        }), 500

@scheduler_bp.route('/scheduler/stop', methods=['POST'])
def stop_scheduled_fetching():
    """
    Stop the hourly signal fetching scheduler.
    """
    try:
        if not is_scheduler_running():
            return jsonify({
                'success': False,
                'message': 'Scheduler is not running'
            }), 400
        
        stop_scheduler()
        
        return jsonify({
            'success': True,
            'message': 'Hourly signal fetching scheduler stopped successfully'
        })
        
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        return jsonify({
            'success': False,
            'message': f'Error stopping scheduler: {str(e)}'
        }), 500

@scheduler_bp.route('/scheduler/status', methods=['GET'])
def get_scheduler_status():
    """
    Get the current status of the scheduler.
    """
    try:
        running = is_scheduler_running()
        
        return jsonify({
            'success': True,
            'running': running,
            'message': 'Scheduler is running' if running else 'Scheduler is stopped'
        })
        
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return jsonify({
            'success': False,
            'message': f'Error getting scheduler status: {str(e)}'
        }), 500

