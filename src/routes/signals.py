from flask import Blueprint, request, jsonify, Response
from src.models.signal import db, RawArticle, ProcessedArticle, ProcessedArticleID, UserConfig
from src.services.eios_fetcher import EIOSFetcher
from src.services.signal_processor import ArticleProcessor
from sqlalchemy import or_, and_
import logging
import csv
import io
from datetime import datetime, timedelta

logger = logging.getLogger("signals_routes")

def parse_datetime_filter(date_str):
    """
    Parse date/datetime string from frontend filters.
    Supports multiple formats:
    - UTC ISO format: YYYY-MM-DDTHH:MM:SS.sssZ (from frontend UTC conversion)
    - Local datetime format: YYYY-MM-DDTHH:MM (legacy)
    - Date-only format: YYYY-MM-DD (legacy)
    Returns datetime object or None if invalid.
    """
    if not date_str:
        return None
    
    try:
        # Try UTC ISO format first (from frontend UTC conversion)
        if date_str.endswith('Z') or '+' in date_str[-6:] or date_str.count(':') == 2:
            # Handle ISO format with fromisoformat (Python 3.7+)
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Try datetime-local format (YYYY-MM-DDTHH:MM)
        elif 'T' in date_str and date_str.count(':') == 1:
            return datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        # Fall back to date-only format (YYYY-MM-DD)
        else:
            return datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, AttributeError):
        return None

signals_bp = Blueprint('signals', __name__)

@signals_bp.route('/articles/fetch', methods=['POST'])
def fetch_articles():
    """
    Trigger manual article fetching and processing.
    """
    try:
        # Get user-defined tags
        tags_config = UserConfig.query.filter_by(key='tags').first()
        if tags_config and tags_config.value:
            tags = [tag.strip() for tag in tags_config.value.split(',') if tag.strip()]
        else:
            # Default tags if none configured
            tags = ["ephem emro"]
        
        logger.info(f"Fetching articles with tags: {tags}")
        
        # Fetch articles from EIOS
        fetcher = EIOSFetcher()
        articles = fetcher.fetch_articles(tags)
        
        if not articles:
            return jsonify({
                'success': True,
                'message': 'No new articles found',
                'processed_count': 0,
                'true_articles_count': 0
            })
        
        # Process ALL articles (no hard cap)
        processor = ArticleProcessor()
        processed_articles = processor.process_articles_batch(articles, batch_size=None)
        
        # Count true signals (is_signal = 'Yes')
        true_signals_count = sum(1 for article in processed_articles if article.is_signal == 'Yes')
        
        return jsonify({
            'success': True,
            'message': f'Successfully processed {len(processed_articles)} articles',
            'processed_count': len(processed_articles),
            'true_signals_count': true_signals_count
        })
        
    except Exception as e:
        logger.error(f"Error fetching articles: {e}")
        return jsonify({
            'success': False,
            'message': f'Error fetching articles: {str(e)}'
        }), 500

@signals_bp.route('/signals/processed', methods=['GET'])
def get_processed_signals():
    """
    Retrieve processed signals for display with optional filtering by status, signal flag and search term.

    Query parameters:
        status: one of 'all', 'new', 'flagged', 'discarded' (default 'all')
        signals_only: boolean flag to include only true signals (is_signal == 'Yes')
        pinned_filter: one of 'all', 'pinned', 'unpinned' (default 'all')
        combined_filters: comma-separated list of filters: 'pinned', 'unpinned', 'flagged', 'unflagged', 'true_signal', 'not_signal'
        search: optional free text to search across raw and processed signal fields
        page: page number for pagination (default 1)
        page_size: number of records per page (default 20)
        countries: comma-separated list of countries to filter by
        start_date: start date for process date filtering (YYYY-MM-DD or YYYY-MM-DDTHH:MM format)
        end_date: end date for process date filtering (YYYY-MM-DD or YYYY-MM-DDTHH:MM format)
    """
    try:
        # Get query parameters
        status_filter = request.args.get('status', 'all')  # 'all', 'new', 'flagged', 'discarded'
        signals_only = request.args.get('signals_only', 'false').lower() == 'true'
        pinned_filter = request.args.get('pinned_filter', 'all')  # 'all', 'pinned', 'unpinned'
        combined_filters = request.args.get('combined_filters', None)  # comma-separated filter list
        search_term = request.args.get('search', None)
        
        # Pagination parameters
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        
        # New filtering parameters
        countries_filter = request.args.get('countries', None)
        hazards_filter = request.args.get('hazards', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)

        # Build query
        query = ProcessedArticle.query

        # Include only true signals if requested
        if signals_only:
            query = query.filter(ProcessedArticle.is_signal == 'Yes')

        # Filter by status if not 'all'
        if status_filter != 'all':
            query = query.filter(ProcessedArticle.status == status_filter)

        # Filter by pinned status if not 'all'
        if pinned_filter == 'pinned':
            query = query.filter(ProcessedArticle.is_pinned == True)
        elif pinned_filter == 'unpinned':
            query = query.filter(ProcessedArticle.is_pinned == False)

        # Handle combined filters (takes precedence over individual filters if provided)
        if combined_filters:
            filter_list = [f.strip().lower() for f in combined_filters.split(',') if f.strip()]
            filter_conditions = []
            
            for filter_item in filter_list:
                if filter_item == 'pinned':
                    filter_conditions.append(ProcessedArticle.is_pinned == True)
                elif filter_item == 'unpinned':
                    filter_conditions.append(ProcessedArticle.is_pinned == False)
                elif filter_item == 'flagged':
                    filter_conditions.append(ProcessedArticle.status == 'flagged')
                elif filter_item == 'unflagged':
                    filter_conditions.append(ProcessedArticle.status.in_(['new', 'discarded']))
                elif filter_item == 'true_signal':
                    filter_conditions.append(ProcessedArticle.is_signal == 'Yes')
                elif filter_item == 'not_signal':
                    filter_conditions.append(ProcessedArticle.is_signal == 'No')
            
            if filter_conditions:
                query = query.filter(and_(*filter_conditions))

        # Filter by countries if provided
        if countries_filter:
            countries_list = [c.strip() for c in countries_filter.split(',') if c.strip()]
            if countries_list:
                country_conditions = []
                for country in countries_list:
                    country_conditions.append(ProcessedArticle.extracted_countries.ilike(f'%{country}%'))
                query = query.filter(or_(*country_conditions))

        # Filter by hazards if provided
        if hazards_filter:
            hazards_list = [h.strip() for h in hazards_filter.split(',') if h.strip()]
            if hazards_list:
                hazard_conditions = []
                for hazard in hazards_list:
                    hazard_conditions.append(ProcessedArticle.extracted_hazards.ilike(f'%{hazard}%'))
                query = query.filter(or_(*hazard_conditions))

        # Filter by date range if provided
        if start_date:
            start_dt = parse_datetime_filter(start_date)
            if start_dt:
                query = query.filter(ProcessedArticle.processed_at >= start_dt)
                
        if end_date:
            end_dt = parse_datetime_filter(end_date)
            if end_dt:
                # If it's a date-only filter, add one day to include the entire end date
                # If it's a datetime filter, use as-is for precise hourly filtering
                if 'T' not in end_date:
                    end_dt = end_dt + timedelta(days=1)
                query = query.filter(ProcessedArticle.processed_at < end_dt)

        # Apply search across multiple fields if a search term is provided. Join with RawArticle to
        # search titles and summaries. Using ilike for case-insensitive partial matching.
        if search_term:
            # Escape percent signs in search term if present
            escaped = search_term.replace('%', '\\%').replace('_', '\\_')
            pattern = f"%{escaped}%"
            query = query.join(RawArticle, ProcessedArticle.raw_article).filter(
                or_(
                    RawArticle.original_title.ilike(pattern),
                    RawArticle.title.ilike(pattern),
                    RawArticle.translated_description.ilike(pattern),
                    RawArticle.translated_abstractive_summary.ilike(pattern),
                    RawArticle.abstractive_summary.ilike(pattern),
                    ProcessedArticle.extracted_countries.ilike(pattern),
                    ProcessedArticle.extracted_hazards.ilike(pattern),
                    ProcessedArticle.risk_signal_assessment.ilike(pattern)
                )
            )

        # Get total count before pagination
        total_count = query.count()
        
        # Calculate total pages
        total_pages = (total_count + page_size - 1) // page_size

        # Order by processed_at descending and apply pagination
        signals = query.order_by(ProcessedArticle.processed_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return jsonify({
            'success': True,
            'signals': [signal.to_dict() for signal in signals],
            'count': len(signals),
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })

    except Exception as e:
        logger.error(f"Error retrieving processed signals: {e}")
        return jsonify({
            'success': False,
            'message': f'Error retrieving signals: {str(e)}'
        }), 500

@signals_bp.route('/signals/tags', methods=['GET', 'POST'])
def manage_tags():
    """
    Get or update user-defined tags.
    """
    if request.method == 'GET':
        try:
            tags_config = UserConfig.query.filter_by(key='tags').first()
            tags = [tag.strip() for tag in tags_config.value.split(",") if tag.strip()] if tags_config and tags_config.value else ["ephem emro"]
            
            return jsonify({
                "success": True,
                "tags": tags
            })
            
        except Exception as e:
            logger.error(f"Error retrieving tags: {e}")
            return jsonify({
                'success': False,
                'message': f'Error retrieving tags: {str(e)}'
            }), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            tags = data.get('tags', '').strip()
            
            # Validate tags format (comma-separated)
            if not tags:
                return jsonify({
                    'success': False,
                    'message': 'Tags cannot be empty'
                }), 400
            
            # Update or create tags configuration
            tags_config = UserConfig.query.filter_by(key='tags').first()
            if tags_config:
                tags_config.value = tags
            else:
                tags_config = UserConfig(key='tags', value=tags)
                db.session.add(tags_config)
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Tags updated successfully',
                'tags': tags
            })
            
        except Exception as e:
            logger.error(f"Error updating tags: {e}")
            return jsonify({
                'success': False,
                'message': f'Error updating tags: {str(e)}'
            }), 500

@signals_bp.route('/signals/config', methods=['GET', 'POST'])
def manage_config():
    """
    Get or update configuration values for the AI provider, API settings and risk prompt.

    GET: Returns current values for provider (AI_PROVIDER), per‑provider API keys/bases,
    model (AI_MODEL) and risk evaluation prompt. Missing values are returned as empty strings.

    POST: Accepts any combination of configuration fields and updates them accordingly. Supported
    JSON keys include:
        - provider: one of "openai", "deepseek" or "local"
        - openai_api_key, openai_api_base
        - deepseek_api_key, deepseek_api_base
        - local_api_key, local_api_base
        - ai_model
        - risk_prompt (alias risk_evaluation_prompt)
        - api_key, api_base: legacy names for OpenAI settings
    """
    if request.method == 'GET':
        try:
            # Helper to fetch config values; return empty string if missing
            def get_cfg(key):
                entry = UserConfig.query.filter_by(key=key).first()
                return entry.value if entry else ''

            config = {
                'provider': get_cfg('AI_PROVIDER') or 'openai',
                'openai_api_key': get_cfg('OPENAI_API_KEY'),
                'openai_api_base': get_cfg('OPENAI_API_BASE'),
                'deepseek_api_key': get_cfg('DEEPSEEK_API_KEY'),
                'deepseek_api_base': get_cfg('DEEPSEEK_API_BASE'),
                'local_api_key': get_cfg('LOCAL_LLM_API_KEY'),
                'local_api_base': get_cfg('LOCAL_LLM_API_BASE'),
                'ai_model': get_cfg('AI_MODEL'),
                'risk_prompt': get_cfg('risk_evaluation_prompt')
            }
            return jsonify({'success': True, 'config': config})
        except Exception as e:
            logger.error(f"Error retrieving config: {e}")
            return jsonify({'success': False, 'message': f'Error retrieving config: {str(e)}'}), 500

    elif request.method == 'POST':
        try:
            data = request.get_json() or {}

            # Map incoming JSON keys to UserConfig keys
            key_map = {
                'provider': 'AI_PROVIDER',
                'openai_api_key': 'OPENAI_API_KEY',
                'openai_api_base': 'OPENAI_API_BASE',
                'deepseek_api_key': 'DEEPSEEK_API_KEY',
                'deepseek_api_base': 'DEEPSEEK_API_BASE',
                'local_api_key': 'LOCAL_LLM_API_KEY',
                'local_api_base': 'LOCAL_LLM_API_BASE',
                'ai_model': 'AI_MODEL',
                # Legacy keys for backward compatibility (OpenAI only)
                'api_key': 'OPENAI_API_KEY',
                'api_base': 'OPENAI_API_BASE',
                'risk_prompt': 'risk_evaluation_prompt',
                'risk_evaluation_prompt': 'risk_evaluation_prompt'
            }

            # Helper to set or update a config value
            def set_config(cfg_key, value):
                if value is None:
                    return
                # Convert booleans/other types to strings for storage
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                config_entry = UserConfig.query.filter_by(key=cfg_key).first()
                if config_entry:
                    config_entry.value = value
                else:
                    config_entry = UserConfig(key=cfg_key, value=value)
                    db.session.add(config_entry)

            # Iterate through provided data and update corresponding config entries
            for incoming_key, incoming_value in data.items():
                if incoming_key in key_map:
                    set_config(key_map[incoming_key], incoming_value)

            db.session.commit()
            return jsonify({'success': True, 'message': 'Configuration updated successfully'})
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return jsonify({'success': False, 'message': f'Error updating config: {str(e)}'}), 500

@signals_bp.route('/signals/<int:signal_id>/flag', methods=['POST'])
def flag_signal(signal_id):
    """
    Flag a specific signal.
    """
    try:
        signal = ProcessedArticle.query.get_or_404(signal_id)
        signal.status = 'flagged'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Signal {signal_id} flagged successfully'
        })
        
    except Exception as e:
        logger.error(f"Error flagging signal {signal_id}: {e}")
        return jsonify({
            'success': False,
            'message': f'Error flagging signal: {str(e)}'
        }), 500

@signals_bp.route('/signals/<int:signal_id>/discard', methods=['POST'])
def discard_signal(signal_id):
    """
    Discard a specific signal.
    """
    try:
        signal = ProcessedArticle.query.get_or_404(signal_id)
        signal.status = 'discarded'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Signal {signal_id} discarded successfully'
        })
        
    except Exception as e:
        logger.error(f"Error discarding signal {signal_id}: {e}")
        return jsonify({
            'success': False,
            'message': f'Error discarding signal: {str(e)}'
        }), 500

@signals_bp.route('/signals/discard-non-flagged', methods=['POST'])
def discard_non_flagged_signals():
    """
    Discard all non-flagged signals that are currently 'new'.
    """
    try:
        # Update all 'new' signals to 'discarded'
        updated_count = ProcessedArticle.query.filter_by(status='new').update({'status': 'discarded'})
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully discarded {updated_count} non-flagged signals'
        })
        
    except Exception as e:
        logger.error(f"Error discarding non-flagged signals: {e}")
        return jsonify({
            'success': False,
            'message': f'Error discarding signals: {str(e)}'
        }), 500

@signals_bp.route('/signals/batch-action', methods=['POST'])
def batch_action_signals():
    """
    Perform batch actions on multiple signals.
    """
    try:
        data = request.get_json()
        signal_ids = data.get('signal_ids', [])
        action = data.get('action')  # 'flag' or 'discard'
        
        if not signal_ids or not action:
            return jsonify({
                'success': False,
                'message': 'signal_ids and action are required'
            }), 400
        
        if action not in ['flag', 'discard']:
            return jsonify({
                'success': False,
                'message': 'action must be either "flag" or "discard"'
            }), 400
        
        # Update signals
        status = 'flagged' if action == 'flag' else 'discarded'
        updated_count = ProcessedArticle.query.filter(ProcessedArticle.id.in_(signal_ids)).update(
            {'status': status}, synchronize_session=False)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully {action}ged {updated_count} signals'
        })
        
    except Exception as e:
        logger.error(f"Error performing batch action: {e}")
        return jsonify({
            'success': False,
            'message': f'Error performing batch action: {str(e)}'
        }), 500


# -----------------------------------------------------------------------------
# Additional API Endpoints for counts and aggregated statistics
# -----------------------------------------------------------------------------

@signals_bp.route('/signals/counts', methods=['GET'])
def get_signal_counts():
    """
    Return counts of processed signals by status. Accepts an optional
    `signals_only` query parameter (true/false) to include only true signals.
    Example response:
    {
        "success": true,
        "counts": {
            "new": 10,
            "flagged": 5,
            "discarded": 3,
            "all": 18
        }
    }
    """
    try:
        signals_only = request.args.get('signals_only', 'false').lower() == 'true'
        base_query = ProcessedArticle.query
        if signals_only:
            base_query = base_query.filter(ProcessedArticle.is_signal == 'Yes')
        counts = {}
        # Total count
        counts['all'] = base_query.count()
        for status in ['new', 'flagged', 'discarded']:
            counts[status] = base_query.filter(ProcessedArticle.status == status).count()
        return jsonify({'success': True, 'counts': counts})
    except Exception as e:
        logger.error(f"Error retrieving signal counts: {e}")
        return jsonify({'success': False, 'message': f'Error retrieving counts: {str(e)}'}), 500


@signals_bp.route('/signals/stats', methods=['GET'])
def get_signal_stats():
    """
    Provide aggregated statistics for use in a dashboard. Returns counts by status,
    counts of true/false signals, and top countries and hazards. The optional
    `top_n` query parameter controls how many countries/hazards to return (default 10).

    Query parameters:
        top_n: number of top countries/hazards to return (default 10, 0 for all)
        start_date: start date for filtering (YYYY-MM-DD format)
        end_date: end date for filtering (YYYY-MM-DD format)
        is_signal: filter by signal flag ('Yes', 'No', or 'all')

    Example response:
    {
        "success": true,
        "counts": {"new": 10, "flagged": 5, "discarded": 3, "all": 18},
        "is_signal_counts": {"Yes": 12, "No": 6},
        "top_countries": [{"country": "USA", "count": 4}, ...],
        "top_hazards": [{"hazard": "outbreak", "count": 5}, ...]
    }
    """
    try:
        from collections import Counter
        top_n = request.args.get('top_n', 10)
        try:
            top_n = int(top_n)
        except ValueError:
            top_n = 10

        # Get filters
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        is_signal_filter = request.args.get('is_signal', 'all')

        # Base query for processed signals
        query = ProcessedArticle.query
        
        # Apply date filtering if provided
        if start_date:
            start_dt = parse_datetime_filter(start_date)
            if start_dt:
                query = query.filter(ProcessedArticle.processed_at >= start_dt)
                
        if end_date:
            end_dt = parse_datetime_filter(end_date)
            if end_dt:
                # If it's a date-only filter, add one day to include the entire end date
                # If it's a datetime filter, use as-is for precise hourly filtering
                if 'T' not in end_date:
                    end_dt = end_dt + timedelta(days=1)
                query = query.filter(ProcessedArticle.processed_at < end_dt)

        # Filter by signal flag if requested
        if is_signal_filter in ['Yes', 'No']:
            query = query.filter(ProcessedArticle.is_signal == is_signal_filter)

        signals = query.all()

        # Counts by status
        counts = {'new': 0, 'flagged': 0, 'discarded': 0}
        is_signal_counts = {'Yes': 0, 'No': 0}
        pinned_counts = {'pinned': 0, 'unpinned': 0}
        country_counter = Counter()
        hazard_counter = Counter()
        for s in signals:
            counts[s.status] = counts.get(s.status, 0) + 1
            is_signal_counts[s.is_signal] = is_signal_counts.get(s.is_signal, 0) + 1
            # Count pinned status
            if s.is_pinned:
                pinned_counts['pinned'] += 1
            else:
                pinned_counts['unpinned'] += 1
            # Count countries
            if s.extracted_countries:
                for c in [c.strip() for c in s.extracted_countries.split(';') if c.strip()]:
                    country_counter[c] += 1
            # Count hazards
            if s.extracted_hazards:
                for h in [h.strip() for h in s.extracted_hazards.split(';') if h.strip()]:
                    hazard_counter[h] += 1

        # Total signals
        counts['all'] = sum(counts.values())

        # Prepare top lists
        if top_n and top_n > 0:
            country_items = country_counter.most_common(top_n)
            hazard_items = hazard_counter.most_common(top_n)
        else:
            country_items = country_counter.most_common()
            hazard_items = hazard_counter.most_common()

        top_countries = [{'country': k, 'count': v} for k, v in country_items]
        top_hazards = [{'hazard': k, 'count': v} for k, v in hazard_items]

        return jsonify({
            'success': True,
            'counts': counts,
            'is_signal_counts': is_signal_counts,
            'pinned_counts': pinned_counts,
            'top_countries': top_countries,
            'top_hazards': top_hazards
        })
    except Exception as e:
        logger.error(f"Error retrieving stats: {e}")
        return jsonify({'success': False, 'message': f'Error retrieving stats: {str(e)}'}), 500



@signals_bp.route('/signals/countries', methods=['GET'])
def get_countries():
    """Return unique countries from processed signals applying optional filters."""
    try:
        # Optional filters
        status_filter = request.args.get('status', 'all')
        search_term = request.args.get('search', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        is_signal = request.args.get('is_signal', 'all')
        hazards_filter = request.args.get('hazards', None)

        query = ProcessedArticle.query

        if is_signal in ('Yes', 'No'):
            query = query.filter(ProcessedArticle.is_signal == is_signal)

        if status_filter != 'all':
            query = query.filter(ProcessedArticle.status == status_filter)

        if start_date:
            start_dt = parse_datetime_filter(start_date)
            if start_dt:
                query = query.filter(ProcessedArticle.processed_at >= start_dt)

        if end_date:
            end_dt = parse_datetime_filter(end_date)
            if end_dt:
                if 'T' not in end_date:
                    end_dt = end_dt + timedelta(days=1)
                query = query.filter(ProcessedArticle.processed_at < end_dt)

        # Filter by hazards if provided
        if hazards_filter:
            hazards_list = [h.strip() for h in hazards_filter.split(',') if h.strip()]
            if hazards_list:
                hazard_conditions = []
                for hazard in hazards_list:
                    hazard_conditions.append(ProcessedArticle.extracted_hazards.ilike(f'%{hazard}%'))
                query = query.filter(or_(*hazard_conditions))

        if search_term:
            escaped = search_term.replace('%', '\\%').replace('_', '\\_')
            pattern = f"%{escaped}%"
            query = query.join(RawArticle, ProcessedArticle.raw_article).filter(
                or_(
                    RawArticle.original_title.ilike(pattern),
                    RawArticle.title.ilike(pattern),
                    RawArticle.translated_description.ilike(pattern),
                    RawArticle.translated_abstractive_summary.ilike(pattern),
                    RawArticle.abstractive_summary.ilike(pattern),
                    ProcessedArticle.extracted_countries.ilike(pattern),
                    ProcessedArticle.extracted_hazards.ilike(pattern),
                    ProcessedArticle.risk_signal_assessment.ilike(pattern)
                )
            )

        signals = query.filter(ProcessedArticle.extracted_countries.isnot(None)).all()

        countries_set = set()
        for signal in signals:
            if signal.extracted_countries:
                countries = [c.strip() for c in signal.extracted_countries.split(';') if c.strip()]
                countries_set.update(countries)

        countries_list = sorted(list(countries_set))

        return jsonify({'success': True, 'countries': countries_list})

    except Exception as e:
        logger.error(f"Error retrieving countries: {e}")
        return jsonify({'success': False, 'message': f'Error retrieving countries: {str(e)}'}), 500


@signals_bp.route('/signals/hazards', methods=['GET'])
def get_hazards():
    """Return unique hazards from processed signals applying optional filters."""
    try:
        # Optional filters
        status_filter = request.args.get('status', 'all')
        search_term = request.args.get('search', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        is_signal = request.args.get('is_signal', 'all')
        countries_filter = request.args.get('countries', None)

        query = ProcessedArticle.query

        if is_signal in ('Yes', 'No'):
            query = query.filter(ProcessedArticle.is_signal == is_signal)

        if status_filter != 'all':
            query = query.filter(ProcessedArticle.status == status_filter)

        if start_date:
            start_dt = parse_datetime_filter(start_date)
            if start_dt:
                query = query.filter(ProcessedArticle.processed_at >= start_dt)

        if end_date:
            end_dt = parse_datetime_filter(end_date)
            if end_dt:
                if 'T' not in end_date:
                    end_dt = end_dt + timedelta(days=1)
                query = query.filter(ProcessedArticle.processed_at < end_dt)

        # Filter by countries if provided
        if countries_filter:
            countries_list = [c.strip() for c in countries_filter.split(',') if c.strip()]
            if countries_list:
                country_conditions = []
                for country in countries_list:
                    country_conditions.append(ProcessedArticle.extracted_countries.ilike(f'%{country}%'))
                query = query.filter(or_(*country_conditions))

        if search_term:
            escaped = search_term.replace('%', '\\%').replace('_', '\\_')
            pattern = f"%{escaped}%"
            query = query.join(RawArticle, ProcessedArticle.raw_article).filter(
                or_(
                    RawArticle.original_title.ilike(pattern),
                    RawArticle.title.ilike(pattern),
                    RawArticle.translated_description.ilike(pattern),
                    RawArticle.translated_abstractive_summary.ilike(pattern),
                    RawArticle.abstractive_summary.ilike(pattern),
                    ProcessedArticle.extracted_countries.ilike(pattern),
                    ProcessedArticle.extracted_hazards.ilike(pattern),
                    ProcessedArticle.risk_signal_assessment.ilike(pattern)
                )
            )

        signals = query.filter(ProcessedArticle.extracted_hazards.isnot(None)).all()

        hazards_set = set()
        for signal in signals:
            if signal.extracted_hazards:
                hazards = [h.strip() for h in signal.extracted_hazards.split(';') if h.strip()]
                hazards_set.update(hazards)

        hazards_list = sorted(list(hazards_set))

        return jsonify({'success': True, 'hazards': hazards_list})

    except Exception as e:
        logger.error(f"Error retrieving hazards: {e}")
        return jsonify({'success': False, 'message': f'Error retrieving hazards: {str(e)}'}), 500


@signals_bp.route('/signals/cleanup', methods=['POST'])
def cleanup_old_signals():
    """
    Remove old signals based on process date.
    
    Request body:
        cutoff_date: date before which signals should be removed (YYYY-MM-DD format)
        confirm: boolean flag to confirm the operation
    """
    try:
        data = request.get_json()
        cutoff_date = data.get('cutoff_date')
        confirm = data.get('confirm', False)
        
        if not cutoff_date:
            return jsonify({
                'success': False,
                'message': 'cutoff_date is required'
            }), 400
            
        if not confirm:
            return jsonify({
                'success': False,
                'message': 'confirm flag must be set to true'
            }), 400
        
        from datetime import datetime
        try:
            cutoff_dt = datetime.strptime(cutoff_date, '%Y-%m-%d')
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Use YYYY-MM-DD'
            }), 400
        
        # Count signals to be deleted
        signals_to_delete = ProcessedArticle.query.filter(ProcessedArticle.processed_at < cutoff_dt).all()
        signal_ids = [s.id for s in signals_to_delete]
        
        # Get associated raw signal IDs
        raw_article_ids = [s.raw_article_id for s in signals_to_delete if s.raw_article_id]
        
        # Delete processed signals
        deleted_processed = ProcessedArticle.query.filter(ProcessedArticle.processed_at < cutoff_dt).delete()
        
        # Delete associated raw signals
        deleted_raw = 0
        if raw_article_ids:
            deleted_raw = RawArticle.query.filter(RawArticle.id.in_(raw_article_ids)).delete(synchronize_session=False)
        
        # Delete processed signal IDs
        deleted_ids = ProcessedArticleID.query.filter(ProcessedArticleID.processed_at < cutoff_dt).delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully cleaned up old signals',
            'deleted_counts': {
                'processed_signals': deleted_processed,
                'raw_signals': deleted_raw,
                'processed_signal_ids': deleted_ids
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning up signals: {e}")
        return jsonify({
            'success': False,
            'message': f'Error cleaning up signals: {str(e)}'
        }), 500

@signals_bp.route('/signals/cleanup/preview', methods=['POST'])
def preview_cleanup():
    """
    Preview what would be deleted in a cleanup operation.
    
    Request body:
        cutoff_date: date before which signals would be removed (YYYY-MM-DD format)
    """
    try:
        data = request.get_json()
        cutoff_date = data.get('cutoff_date')
        
        if not cutoff_date:
            return jsonify({
                'success': False,
                'message': 'cutoff_date is required'
            }), 400
        
        from datetime import datetime
        try:
            cutoff_dt = datetime.strptime(cutoff_date, '%Y-%m-%d')
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Use YYYY-MM-DD'
            }), 400
        
        # Count signals that would be deleted
        processed_count = ProcessedArticle.query.filter(ProcessedArticle.processed_at < cutoff_dt).count()
        
        # Count raw signals that would be deleted
        signals_to_delete = ProcessedArticle.query.filter(ProcessedArticle.processed_at < cutoff_dt).all()
        raw_article_ids = [s.raw_article_id for s in signals_to_delete if s.raw_article_id]
        raw_count = len(raw_article_ids)
        
        # Count processed signal IDs that would be deleted
        ids_count = ProcessedArticleID.query.filter(ProcessedArticleID.processed_at < cutoff_dt).count()
        
        return jsonify({
            'success': True,
            'preview': {
                'cutoff_date': cutoff_date,
                'counts_to_delete': {
                    'processed_signals': processed_count,
                    'raw_signals': raw_count,
                    'processed_signal_ids': ids_count
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error previewing cleanup: {e}")
        return jsonify({
            'success': False,
            'message': f'Error previewing cleanup: {str(e)}'
        }), 500


@signals_bp.route('/signals/export-csv', methods=['POST'])
def export_signals_csv():
    """
    Export selected signals to CSV format.
    
    Request body should contain:
    {
        "signal_ids": [1, 2, 3, ...] or "all" for all signals with current filters
        "filters": {
            "status": "all|new|flagged|discarded",
            "pinned_filter": "all|pinned|unpinned", 
            "signals_only": true|false,
            "search": "search term",
            "countries": "country1,country2",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD"
        }
    }
    """
    try:
        data = request.get_json()
        signal_ids = data.get('signal_ids', [])
        filters = data.get('filters', {})
        
        # Build query based on filters or specific IDs
        if signal_ids == "all":
            # Apply filters to get all matching signals
            query = ProcessedArticle.query
            
            status_filter = filters.get('status', 'all')
            pinned_filter = filters.get('pinned_filter', 'all')
            signals_only = filters.get('signals_only', False)
            search_term = filters.get('search')
            countries_filter = filters.get('countries')
            hazards_filter = filters.get('hazards')
            start_date = filters.get('start_date')
            end_date = filters.get('end_date')
            
            # Apply filters (same logic as get_processed_signals)
            if signals_only:
                query = query.filter(ProcessedArticle.is_signal == 'Yes')
            
            if status_filter != 'all':
                query = query.filter(ProcessedArticle.status == status_filter)
            
            if pinned_filter == 'pinned':
                query = query.filter(ProcessedArticle.is_pinned == True)
            elif pinned_filter == 'unpinned':
                query = query.filter(ProcessedArticle.is_pinned == False)
            
            if countries_filter:
                countries_list = [c.strip() for c in countries_filter.split(',') if c.strip()]
                if countries_list:
                    country_conditions = []
                    for country in countries_list:
                        country_conditions.append(ProcessedArticle.extracted_countries.ilike(f'%{country}%'))
                    query = query.filter(or_(*country_conditions))
            
            if hazards_filter:
                hazards_list = [h.strip() for h in hazards_filter.split(',') if h.strip()]
                if hazards_list:
                    hazard_conditions = []
                    for hazard in hazards_list:
                        hazard_conditions.append(ProcessedArticle.extracted_hazards.ilike(f'%{hazard}%'))
                    query = query.filter(or_(*hazard_conditions))
            
            if start_date:
                start_dt = parse_datetime_filter(start_date)
                if start_dt:
                    query = query.filter(ProcessedArticle.processed_at >= start_dt)
            
            if end_date:
                end_dt = parse_datetime_filter(end_date)
                if end_dt:
                    if 'T' not in end_date:
                        end_dt = end_dt + timedelta(days=1)
                    query = query.filter(ProcessedArticle.processed_at < end_dt)
            
            if search_term:
                escaped = search_term.replace('%', '\\%').replace('_', '\\_')
                pattern = f"%{escaped}%"
                query = query.join(RawArticle, ProcessedArticle.raw_article).filter(
                    or_(
                        RawArticle.original_title.ilike(pattern),
                        RawArticle.title.ilike(pattern),
                        RawArticle.translated_description.ilike(pattern),
                        RawArticle.translated_abstractive_summary.ilike(pattern),
                        RawArticle.abstractive_summary.ilike(pattern),
                        ProcessedArticle.extracted_countries.ilike(pattern),
                        ProcessedArticle.extracted_hazards.ilike(pattern)
                    )
                )
            
            signals = query.order_by(ProcessedArticle.processed_at.desc()).all()
        else:
            # Get specific signals by IDs
            signals = ProcessedArticle.query.filter(ProcessedArticle.id.in_(signal_ids)).all()
        
        if not signals:
            return jsonify({
                'success': False,
                'message': 'No signals found for export'
            }), 400
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # CSV Headers
        headers = [
            'ID', 'RSS Item ID', 'Title', 'Original Title', 'Translated Description',
            'Translated Summary', 'Summary', 'Countries', 'Is Signal', 'Justification',
            'Hazards', 'Vulnerability Score', 'Coping Score', 'Total Risk Score',
            'Status', 'Is Pinned', 'Processed Date', 'Created Date', 'EIOS URL'
        ]
        writer.writerow(headers)
        
        # Write data rows
        for signal in signals:
            raw_article = signal.raw_article
            eios_url = f"https://portal.who.int/eios/#/items/{signal.rss_item_id}/title/full-article"
            
            row = [
                signal.id,
                signal.rss_item_id,
                raw_article.title if raw_article else '',
                raw_article.original_title if raw_article else '',
                raw_article.translated_description if raw_article else '',
                raw_article.translated_abstractive_summary if raw_article else '',
                raw_article.abstractive_summary if raw_article else '',
                signal.extracted_countries or '',
                signal.is_signal or '',
                signal.get_justification(),
                signal.extracted_hazards or '',
                signal.vulnerability_score or '',
                signal.coping_score or '',
                signal.total_risk_score or '',
                signal.status,
                'Yes' if signal.is_pinned else 'No',
                signal.processed_at.strftime('%Y-%m-%d %H:%M:%S') if signal.processed_at else '',
                raw_article.created_at.strftime('%Y-%m-%d %H:%M:%S') if raw_article and raw_article.created_at else '',
                eios_url
            ]
            writer.writerow(row)
        
        # Prepare response
        csv_content = output.getvalue()
        output.close()
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"eios_signals_{timestamp}.csv"
        
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting signals to CSV: {e}")
        return jsonify({
            'success': False,
            'message': f'Error exporting signals: {str(e)}'
        }), 500

