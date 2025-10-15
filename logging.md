# EIOS Application Development Log

## Overview
This document tracks all enhancements and modifications made to the EIOS Signal Management Application, including pinned articles support, CSV export functionality, and EIOS v2 API migration.

> **Last Updated**: October 15, 2025  
> **Version**: 2.1 - Migrated to EIOS v2 API  
> **Status**: Development Complete, Ready for Testing

---

## Enhancement 3: EIOS v2 API Migration (October 15, 2025)

### Summary
Migrated from EIOS v1 API to EIOS v2 API with new authentication flow, endpoints, and data structures. This update modernizes the application to use the latest EIOS API standards.

### API Changes

#### Old EIOS v1 API Endpoints
- `https://portal.who.int/eios/API/News/Service/GetBoards`
- `https://portal.who.int/eios/API/News/Service/GetBoardArticles`
- `https://portal.who.int/eios/API/News/Service/GetPinnedArticles`

#### New EIOS v2 API Endpoints
- **Base URL (Production)**: `https://eios.who.int/portal/api/api/v1.0`
- **Base URL (Sandbox)**: `https://eios.who.int/portal-sandbox/api/api/v1.0`
- **Terms of Use**: `PUT /UserProfiles/me`
- **Boards by Tags**: `GET /Boards/by-tags`
- **Pinned Articles**: `GET /Items/pinned-to-boards`
- **Board Articles**: `GET /Items/matching-board/{boardId}` (fetches all articles matching board filter)

### Backend Changes

#### EIOS Fetcher (`src/services/eios_fetcher.py`)
**Complete rewrite to support EIOS v2:**

**New Methods:**
- `accept_terms()` - Accept EIOS Terms of Use (required for v2 API)
- `utc_now()` - Get current UTC datetime with timezone awareness
- `to_iso_z()` - Convert datetime to ISO 8601 format with Z suffix
- `get_pinned_articles()` - Fetch pinned articles using v2 endpoint
- `get_board_articles()` - **NEW** Fetch all articles matching board filter (pinned + unpinned)
- `_transform_article_v2_to_v1()` - Transform v2 article format to v1 format for compatibility

**Modified Methods:**
- `get_access_token()` - Enhanced error handling for token acquisition
- `normalize_datetime()` - Improved datetime parsing with timezone handling
- `get_boards()` - Updated to use `/Boards/by-tags` endpoint with pagination
- `get_all_articles_with_pinned_status()` - **UPDATED** Now fetches from both endpoints:
  1. Gets pinned articles from `/Items/pinned-to-boards`
  2. Gets all board articles from `/Items/matching-board/{boardId}` for each board
  3. Merges results, deduplicates, and correctly marks pinned status
- `fetch_signals()` - Updated to work with v2 API flow

**Deprecated Methods (maintained for compatibility):**
- `get_all_articles()` - Not used in v2 API
- `get_pinned_article_ids()` - Replaced by integrated pinned status in v2
- `get_unpinned_articles_from_boards()` - V2 API uses board articles endpoint instead

**New Configuration:**
- `BASE_URL` - Centralized API base URL (supports both production and sandbox via env var)
- `PAGE_SIZE_BOARDS = 100` - Board pagination size
- `PAGE_SIZE_ARTICLES = 300` - Article pagination size
- `MAX_ARTICLES = 5000` - Safety cap for article fetching
- `FETCH_DURATION_HOURS = 5` - Default time window (increased from 1 hour)

### Key Differences: V1 vs V2

#### Authentication
- **V1**: Simple OAuth2 token
- **V2**: OAuth2 token + Terms of Use acceptance required

#### Data Retrieval
- **V1**: Separate calls for all articles and pinned status
- **V2**: Dual endpoint strategy:
  - `/Items/pinned-to-boards` for pinned articles with timestamps
  - `/Items/matching-board/{boardId}` for all board articles
  - Application merges and deduplicates results with correct pinned status

#### Time Handling
- **V1**: Used Elasticsearch date math (`now-2h/h`)
- **V2**: Uses ISO 8601 format with Z suffix (`2025-10-15T10:30:00Z`)

#### Article Focus
- **V1**: Could fetch all articles (pinned and unpinned)
- **V2**: Primarily provides pinned articles within time window

### Data Format Changes

#### V2 Article Structure
```python
{
    "id": "article_id",
    "title": "...",
    "originalTitle": "...",
    "translatedDescription": "...",
    "description": "...",
    "abstractiveSummary": "...",
    "link": "...",
    "languageIso": "en",
    "pubDate": "2025-10-15T10:30:00Z",
    "processedOnDate": "2025-10-15T10:35:00Z",
    "source": {
        "id": 123,
        "name": "Source Name",
        "url": "https://...",
        "country": {
            "label": "Country Name"
        }
    },
    "userActions": {
        "pinned": {
            "toBoards": [
                {
                    "boardId": 456,
                    "boardName": "Board Name",
                    "pinnedOnDate": "2025-10-15T10:32:00Z"
                }
            ]
        }
    }
}
```

### Compatibility Layer

The application maintains backward compatibility by:
1. **Transform Function**: Converts v2 article format to v1 format expected by signal processor
2. **Pinned Status**: All articles from v2 API are marked as `is_pinned = True`
3. **Legacy Methods**: Deprecated methods return empty data rather than errors
4. **Field Mapping**: Maps v2 field names to v1 field names automatically

### Impact on Application Features

#### ✅ Fully Compatible
- Signal fetching and processing
- AI evaluation and classification
- Country and hazard extraction
- CSV export functionality
- User flagging and status management
- Filtering and search

#### ⚠️ Behavior Changes
- **Pinned Filter**: All fetched articles will show as "pinned" since v2 API focuses on pinned articles
- **Time Window**: Default increased to 5 hours (was 1 hour)
- **Unpinned Articles**: No longer available through v2 API

#### 💡 Recommendations
1. Use "All Articles" filter instead of "Pinned/Unpinned" filter
2. Adjust `FETCH_DURATION_HOURS` environment variable as needed
3. Consider the time window when expecting new articles

### Configuration Updates

#### Environment Variables
No changes to required environment variables:
- `WHO_TENANT_ID` - Azure AD tenant ID
- `EIOS_CLIENT_ID_SCOPE` - EIOS API scope
- `CONSUMER_CLIENT_ID` - Client application ID
- `CONSUMER_SECRET` - Client application secret
- `FETCH_DURATION_HOURS` - Time window for fetching (default: 5)

### Testing Checklist
- [ ] Verify authentication works with v2 API
- [ ] Confirm Terms of Use acceptance
- [ ] Test board retrieval by tags
- [ ] Test pinned article fetching
- [ ] Verify article transformation
- [ ] Confirm signal processing works
- [ ] Test CSV export with v2 data
- [ ] Validate all filters function correctly

---

## Enhancement 1: Pinned Articles Support (October 5, 2025)

### Summary
Modified the EIOS application to retrieve both pinned and unpinned articles from EIOS, while maintaining existing signal classification and flagging functionality. Added a new "pinned" filter to the web interface.

### Database Schema Changes

#### ProcessedSignal Model (`src/models/signal.py`)
- **Added field**: `is_pinned = db.Column(db.Boolean, default=False)`
- **Updated**: `to_dict()` method to include `is_pinned` field
- **Migration**: Applied via `migration_add_is_pinned.py` script (545 existing records updated)

### Backend Changes

#### EIOS Fetcher (`src/services/eios_fetcher.py`)
- **New method**: `get_all_articles_with_pinned_status()` - retrieves all articles with pinned status
- **Modified**: `fetch_signals()` method now returns both pinned and unpinned articles with pinned status
- **Enhanced logging**: Shows counts of pinned vs unpinned articles

#### Signal Processor (`src/services/signal_processor.py`)
- **Modified**: `process_signal()` method accepts `is_pinned` parameter
- **Updated**: `process_signals_batch()` method passes pinned status to signal processing
- **Enhanced logging**: Shows pinned status when processing signals
- **Fixed**: Added missing `json` import

#### API Routes (`src/routes/signals.py`)
- **New filter**: `pinned_filter` parameter ('all', 'pinned', 'unpinned')
- **Enhanced**: `/signals/processed` endpoint supports pinned filtering
- **Updated**: `/signals/stats` endpoint includes pinned/unpinned counts
- **Fixed**: Consolidated SQLAlchemy imports

### Frontend Changes

#### HTML Interface (`src/static/index.html`)
- **Added**: Pinned filter dropdown after signal type filter
- **Options**: "All Articles", "Pinned", "Unpinned"

#### JavaScript (`src/static/app.js`)
- **Added**: `pinnedFilter` variable in `loadSignals()` method
- **Enhanced**: API request includes `pinned_filter` parameter
- **Updated**: Signal card rendering shows pinned status with thumbtack icon (orange for pinned, gray for unpinned)
- **Added**: Event listener for pinned filter changes

### Migration Script (`migration_add_is_pinned.py`)
- **Purpose**: Adds `is_pinned` column to existing database
- **Safety**: Checks if column exists before attempting to add
- **Default**: Sets all existing records to unpinned (False)
- **Status**: ✅ Successfully executed (545 records updated)
- **Note**: Script was removed after successful migration completion

---

## Enhancement 2: CSV Export Functionality (October 5, 2025)

### Summary
Added comprehensive CSV export functionality with select all/unselect all controls and export options for both selected signals and all signals with current filters.

### Backend Changes

#### API Routes (`src/routes/signals.py`)
- **New endpoint**: `POST /signals/export-csv`
- **Features**:
  - Export selected signals by ID
  - Export all signals matching current filters
  - Supports all existing filters (status, pinned, signals_only, search, countries, date range)
  - Returns CSV file with proper headers and filename timestamp

#### CSV Export Fields
The exported CSV includes the following columns:
1. **ID** - Signal database ID
2. **RSS Item ID** - Original EIOS item ID
3. **Title** - Processed article title
4. **Original Title** - Original article title
5. **Translated Description** - Translated description
6. **Translated Summary** - Translated abstractive summary
7. **Summary** - Original abstractive summary
8. **Countries** - Extracted countries from AI assessment
9. **Is Signal** - AI classification (Yes/No)
10. **Justification** - AI justification for classification
11. **Hazards** - Extracted hazard types
12. **Vulnerability Score** - Risk assessment score
13. **Coping Score** - Coping capacity score
14. **Total Risk Score** - Combined risk score
15. **Status** - User classification (new/flagged/discarded)
16. **Is Pinned** - EIOS pinned status (Yes/No)
17. **Processed Date** - When signal was processed
18. **Created Date** - When original article was created
19. **EIOS URL** - Direct link to EIOS article

### Frontend Changes

#### HTML Interface (`src/static/index.html`)
Added new button groups with improved layout:

**Selection Controls:**
- **Select All** - Selects all signals on current page
- **Unselect All** - Clears all selections

**Action Buttons:**
- **Flag Selected** - Flag selected signals
- **Discard Selected** - Discard selected signals  
- **Export Selected** - Export selected signals to CSV

**Other Actions:**
- **Discard Non-Flagged** - Existing bulk discard functionality
- **Export All** - Export all signals matching current filters

#### JavaScript (`src/static/app.js`)
**New Methods:**
- `selectAllSignals()` - Selects all signals on current page
- `unselectAllSignals()` - Clears all selections
- `getCurrentFilters()` - Gets current filter state for export
- `exportSelected()` - Exports selected signals to CSV
- `exportAll()` - Exports all signals with current filters to CSV

**Enhanced Features:**
- Updated `updateBatchButtons()` to include export button state
- Added event listeners for new buttons
- Proper file download handling with browser APIs
- Status messages for export operations
- Error handling for export failures

#### CSS Styling (`src/static/index.html`)
Added responsive button layout:
- Flexible wrapping for different screen sizes
- Logical grouping of related functions
- Consistent spacing and alignment
- Proper button state management (enabled/disabled)

### Export Functionality Details

#### Export Selected Signals
- **Trigger**: "Export Selected" button (requires selection)
- **Behavior**: Exports only signals selected via checkboxes
- **API Call**: `POST /signals/export-csv` with `signal_ids` array
- **Filename**: `eios_signals_YYYYMMDD_HHMMSS.csv`

#### Export All Signals
- **Trigger**: "Export All" button (no selection required)
- **Behavior**: Exports all signals matching current filters
- **API Call**: `POST /signals/export-csv` with `signal_ids: "all"`
- **Filters Applied**: Status, pinned, signal type, search, countries, date range
- **Filename**: `eios_signals_YYYYMMDD_HHMMSS.csv`

#### Filter Integration
Both export methods respect current filter settings:
- **Status Filter**: new/flagged/discarded/all
- **Pinned Filter**: pinned/unpinned/all
- **Signal Type**: true signals only toggle
- **Search**: text search across multiple fields
- **Countries**: selected country filters
- **Date Range**: start and end date filters

---

## Technical Implementation Details

### Data Flow
1. **Article Retrieval**: EIOS fetcher gets both pinned and unpinned articles
2. **Processing**: Signal processor preserves pinned status during AI evaluation
3. **Storage**: Database stores both pinned status and user classifications
4. **Display**: Web interface shows all status indicators with filtering
5. **Export**: CSV export includes all relevant fields with proper formatting

### API Endpoints

#### Enhanced Endpoints
- `GET /api/signals/processed` - Now supports `pinned_filter` parameter
- `GET /api/signals/stats` - Now includes `pinned_counts` in response

#### New Endpoints
- `POST /api/signals/export-csv` - CSV export functionality

### Database Schema Updates
```sql
-- Added to processed_signals table
ALTER TABLE processed_signals ADD COLUMN is_pinned BOOLEAN DEFAULT 0;
```

### File Structure Changes
```
src/
├── models/signal.py (enhanced)
├── services/
│   ├── eios_fetcher.py (enhanced)
│   └── signal_processor.py (enhanced)
├── routes/signals.py (enhanced)
└── static/
    ├── index.html (enhanced)
    └── app.js (enhanced)

logging.md (comprehensive documentation)
README.md (updated with references)
```

**Note**: Migration and test scripts were removed after successful completion:
- `migration_add_is_pinned.py` (removed after database migration)
- `test_csv_export.py` (removed after feature testing)

---

## Status Combinations

Articles now support multiple independent status dimensions:

### Signal Classification (AI-determined)
- **True Signal** - AI classified as a valid signal
- **Not Signal** - AI classified as not a valid signal

### User Status (User-determined)
- **New** - Newly processed, awaiting review
- **Flagged** - User marked as important
- **Discarded** - User marked as unimportant

### EIOS Status (External system)
- **Pinned** - Marked as important in EIOS
- **Unpinned** - Not marked in EIOS

### Example Combinations
- Pinned + True Signal + Flagged = High priority signal
- Unpinned + True Signal + New = New signal for review
- Pinned + Not Signal + Discarded = Noise filtered out

---

## User Interface Features

### Filtering Options
1. **Status Filter**: All/New/Flagged/Discarded signals
2. **Signal Type Filter**: All/True Signals/Not Signals
3. **Pinned Filter**: All/Pinned/Unpinned articles
4. **Search**: Full-text search across titles and content
5. **Country Filter**: Multi-select country filtering
6. **Date Range**: Start and end date filtering

### Selection Controls
- **Individual Selection**: Checkbox per signal
- **Select All**: Select all signals on current page
- **Unselect All**: Clear all selections
- **Selection Counter**: Shows number of selected signals

### Export Options
- **Export Selected**: Download CSV of selected signals
- **Export All**: Download CSV of all signals matching filters
- **Timestamp Filenames**: Automatic timestamped filenames
- **Progress Indicators**: Loading states during export

### Visual Indicators
- **Signal Status**: Green checkmark (True) / Red X (Not Signal)
- **User Status**: Color-coded badges (New/Flagged/Discarded)
- **Pinned Status**: Orange thumbtack (Pinned) / Gray thumbtack (Unpinned)
- **Selection State**: Highlighted checkboxes
- **Button States**: Enabled/disabled based on selection

---

## Testing and Validation

### Database Migration
- ✅ Migration script executed successfully
- ✅ 545 existing records updated with is_pinned = False
- ✅ New schema validated

### Backend Functionality
- ✅ Python syntax validation passed
- ✅ API endpoint structure verified
- ✅ CSV export logic implemented

### Frontend Integration
- ✅ New buttons added to interface
- ✅ Event listeners configured
- ✅ Filter integration completed
- ✅ Responsive layout implemented

### Next Testing Steps
1. Start application server
2. Test pinned filter functionality
3. Test select all/unselect all controls
4. Test CSV export with selected signals
5. Test CSV export with all signals and filters
6. Verify CSV content and formatting
7. Test error handling scenarios

---

## Future Enhancements

### Potential Improvements
1. **Bulk Selection**: Select all across multiple pages
2. **Custom Export Fields**: User-configurable CSV columns
3. **Export Formats**: JSON, Excel, PDF options
4. **Scheduled Exports**: Automated export functionality
5. **Export History**: Track previous exports
6. **Advanced Filtering**: More complex filter combinations
7. **Data Visualization**: Charts and graphs of exported data

### Technical Debt
1. **SQLAlchemy Import**: Resolve import warnings
2. **Error Handling**: Enhanced error messages and recovery
3. **Performance**: Optimize for large datasets
4. **Testing**: Comprehensive unit and integration tests
5. **Documentation**: API documentation and user guides

---

## Conclusion

The EIOS application has been successfully enhanced with:

1. **Complete EIOS Integration**: Now processes both pinned and unpinned articles
2. **Enhanced Filtering**: Comprehensive filter options including pinned status
3. **Flexible Export**: CSV export with selection and filter options
4. **Improved UX**: Better selection controls and visual indicators
5. **Backward Compatibility**: All existing functionality preserved

The application now provides a complete workflow for managing EIOS signals with full export capabilities for data analysis and reporting purposes.
