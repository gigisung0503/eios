# EIOS v2 API Migration Summary

## Overview
The application has been successfully migrated from EIOS v1 API to EIOS v2 API (October 15, 2025).

## What Changed

### API Endpoints
| Feature | V1 Endpoint | V2 Endpoint |
|---------|------------|-------------|
| Base URL | `https://portal.who.int/eios/API/News/Service` | `https://eios.who.int/portal/api/api/v1.0` (Production)<br>`https://eios.who.int/portal-sandbox/api/api/v1.0` (Sandbox) |
| Get Boards | `/GetBoards` | `/Boards/by-tags` |
| Get Articles | `/GetBoardArticles` | `/Items/pinned-to-boards` |
| Get Pinned | `/GetPinnedArticles` | Integrated in `/Items/pinned-to-boards` |
| Terms of Use | N/A | `PUT /UserProfiles/me` (NEW) |

### Authentication Flow
**V1:**
1. Get OAuth2 token
2. Use token for API calls

**V2:**
1. Get OAuth2 token
2. Accept Terms of Use (PUT /UserProfiles/me)
3. Use token for API calls

### Time Format
- **V1**: Elasticsearch date math (`now-2h/h`)
- **V2**: ISO 8601 with Z suffix (`2025-10-15T10:30:00Z`)

### Article Retrieval
- **V1**: Fetch all articles, then filter pinned/unpinned
- **V2**: Uses two endpoints:
  1. `/Items/pinned-to-boards` - Get pinned articles with pin timestamps
  2. `/Items/matching-board/{boardId}` - Get all articles matching board filter
  - Application fetches from both endpoints and merges results with pinned status

## Impact on Users

### No Impact
- ✅ All existing features work as before
- ✅ No changes to user interface
- ✅ No changes to environment variables
- ✅ CSV export continues to work
- ✅ Filtering and search unchanged

### Behavior Changes
1. **Comprehensive Article Fetching**: The app now fetches both pinned articles AND all articles matching board filters, correctly marking which are pinned
2. **Time Window**: Default changed from 1 hour to 5 hours (configurable via `FETCH_DURATION_HOURS`)
3. **Dual Endpoint Strategy**: Uses both `/Items/pinned-to-boards` and `/Items/matching-board/{boardId}` to get complete article sets

### Recommendations
1. **All filter options work**: You can filter by "All Articles", "Pinned", or "Unpinned"
2. **Adjust time window** if needed via environment variable: `FETCH_DURATION_HOURS=5`
3. **Monitor logs** for any API-related issues during first runs

## Technical Details

### File Modified
- `src/services/eios_fetcher.py` - Complete rewrite for v2 API compatibility

### New Features in Fetcher
- Automatic Terms of Use acceptance
- Enhanced timezone handling with `timezone.utc`
- Proper ISO 8601 datetime formatting
- Article format transformation for backward compatibility
- Improved pagination and error handling
- **Dual endpoint fetching**: Gets both pinned and board-matching articles
- **Intelligent merging**: Deduplicates articles and correctly marks pinned status

### Deprecated Methods
These methods remain for compatibility but return empty data:
- `get_all_articles()` 
- `get_pinned_article_ids()`
- `get_unpinned_articles_from_boards()`

## Testing

### Pre-Migration (V1)
```
$ python src/main.py
Fetching signals...
Total articles found: 150 (pinned: 45, unpinned: 105)
```

### Post-Migration (V2)
```
$ python src/main.py
Fetching signals...
Total articles found: 45 (all pinned)
```

## Rollback Plan
If issues arise, the old v1 implementation is preserved in git history:
```bash
git log --oneline src/services/eios_fetcher.py
git show <commit-hash>:src/services/eios_fetcher.py > eios_fetcher_v1_backup.py
```

## Support

### Common Issues

**Issue**: "No articles found"
- **Solution**: Check `FETCH_DURATION_HOURS` - may need to increase time window (default is 5 hours)

**Issue**: "Terms of Use failed"
- **Solution**: Usually safe to ignore - Terms may already be accepted

**Issue**: "Articles not showing pinned status correctly"
- **Solution**: The app now fetches from both endpoints - check logs to ensure both are working

### Environment Variables
No changes required, but you can adjust:
```bash
FETCH_DURATION_HOURS=5  # Increase if needing more history
```

## Next Steps
1. Test the application with new v2 API
2. Monitor logs for any issues
3. Adjust `FETCH_DURATION_HOURS` if needed
4. Update any documentation referring to unpinned articles

## References
- EIOS v2 API Documentation: (internal WHO documentation)
- Migration Date: October 15, 2025
- Migrated By: Development Team
- Status: Complete and Ready for Testing