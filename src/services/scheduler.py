import threading
import time
import logging
from datetime import datetime
from src.services.eios_fetcher import EIOSFetcher
from src.services.signal_processor import SignalProcessor
from src.models.signal import UserConfig

logger = logging.getLogger("scheduler")

class SignalScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        self.interval = 3600  # 1 hour in seconds
        
    def start(self):
        """Start the scheduler thread."""
        if self.running:
            logger.warning("Scheduler is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Signal scheduler started - will fetch signals every hour")
        
    def stop(self):
        """Stop the scheduler thread."""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("Signal scheduler stopped")
        
    def _run_scheduler(self):
        """Main scheduler loop."""
        while self.running:
            try:
                self._fetch_and_process_signals()
            except Exception as e:
                logger.error(f"Error in scheduled signal processing: {e}")
            
            # Sleep for the interval, but check periodically if we should stop
            sleep_time = 0
            while sleep_time < self.interval and self.running:
                time.sleep(60)  # Check every minute
                sleep_time += 60
                
    def _fetch_and_process_signals(self):
        """Fetch and process signals - same logic as manual trigger."""
        logger.info("Starting scheduled signal fetch and processing")
        try:
            # Import the app within this method to avoid circular imports
            from src.main import app
            # Push the application context for the duration of the scheduled work
            with app.app_context():
                # Get user-defined tags
                from src.models.signal import db
                with db.session.no_autoflush:
                    tags_config = UserConfig.query.filter_by(key='tags').first()
                    if tags_config and tags_config.value:
                        tags = [tag.strip() for tag in tags_config.value.split(',') if tag.strip()]
                    else:
                        # Default tags if none configured
                        tags = ["ephem emro"]
                
                logger.info(f"Fetching signals with tags: {tags}")
                
                # Fetch signals from EIOS
                fetcher = EIOSFetcher()
                articles = fetcher.fetch_signals(tags)
                
                if not articles:
                    logger.info("No new signals found during scheduled fetch")
                    return
                
                # Process signals in batches of 50
                processor = SignalProcessor()
                processed_signals = processor.process_signals_batch(articles, batch_size=None)
                
                # Count true signals (is_signal = 'Yes')
                true_signals_count = sum(1 for signal in processed_signals if signal.is_signal == 'Yes')
                
                logger.info(f"Scheduled processing complete: {len(processed_signals)} processed, {true_signals_count} true signals")
        except Exception as e:
            logger.error(f"Error in scheduled signal processing: {e}")
            raise e

# Global scheduler instance
scheduler_instance = None

def start_scheduler():
    """Start the global scheduler instance."""
    global scheduler_instance
    if scheduler_instance is None:
        scheduler_instance = SignalScheduler()
    scheduler_instance.start()

def stop_scheduler():
    """Stop the global scheduler instance."""
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.stop()

def is_scheduler_running():
    """Check if the scheduler is running."""
    global scheduler_instance
    return scheduler_instance and scheduler_instance.running

