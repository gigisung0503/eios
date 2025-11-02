# EIOS Article Management Application

A streamlined application to read and process EIOS articles, evaluate them for validity as signals, extract country and hazard information, and provide a user interface for managing article flags and discards.

> **📋 Development Log**: For detailed information about recent enhancements including pinned articles support and CSV export functionality, see [logging.md](logging.md).

## Features

- **Article Fetching**: Automatically fetch both pinned and unpinned articles from EIOS using configurable tags
- **AI-Powered Evaluation**: Use OpenAI GPT-4 to evaluate articles for signal validity using risk scoring system
- **Country & Hazard Extraction**: Extract affected countries and hazard types using Sendai Framework
- **Batch Processing**: Process articles in batches to manage API costs
- **User Interface**: Web-based interface for managing articles with comprehensive filtering
- **Scheduling**: Hourly automatic fetching with manual trigger option
- **Persistence**: Avoid reprocessing already processed articles
- **Article Management**: Flag, discard, and filter articles with pinned status support
- **CSV Export**: Export selected or all articles to CSV with comprehensive data fields
- **Enhanced Filtering**: Filter by status, signal type, pinned status, countries, and date ranges

## Installation

1. **Clone or extract the application**:
   ```bash
   cd eios_signal_app
   ```

2. **Activate the virtual environment**:
   ```bash
   source venv/bin/activate
   ```

3. **Install dependencies** (if not already installed):
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   - The `.env` file is already configured with your OpenAI API key
   - Modify `.env` if needed to update API keys or endpoints

## Usage

### Starting the Application

1. **Start the Flask server**:
   ```bash
   cd eios_signal_app
   source venv/bin/activate
   python src/main.py
   ```

2. **Access the web interface**:
   - Open your browser and go to `http://localhost:5000`
   - The application will be running on all interfaces (0.0.0.0:5000)

### Configuration

1. **Configure EIOS Tags**:
   - Click the "Configure" button in the top-right corner
   - Enter comma-separated tags (e.g., "ephem emro, other tag")
   - Default tag is "ephem emro"
   - Click "Save" to apply changes

### Signal Processing

1. **Manual Signal Fetching**:
   - Click "Fetch Signals" to manually trigger signal fetching and processing
   - The system will process up to 50 new signals per batch
   - Processing includes country extraction, hazard identification, and risk scoring

2. **Automatic Scheduling**:
   - Click "Start" next to "Scheduler: Stopped" to enable hourly automatic fetching
   - Click "Stop" to disable automatic fetching
   - Scheduler status is displayed in the header

### Signal Management

1. **View Signals**:
   - All processed signals are displayed in the main interface
   - Use filters to view specific signal types:
     - "All Signals", "New Signals", "Flagged Signals", "Discarded Signals"
     - Toggle "True Signals Only" to show only signals marked as valid

2. **Individual Signal Actions**:
   - Click the flag icon (🏳️) to flag a signal
   - Click the trash icon (🗑️) to discard a signal

3. **Batch Actions**:
   - Select multiple signals using checkboxes
   - Click "Flag Selected" to flag all selected signals
   - Click "Discard Selected" to discard all selected signals
   - Click "Discard Non-Flagged" to discard all signals that haven't been flagged

### Signal Information

Each signal card displays:
- **Title**: Original signal title
- **Status**: New, Flagged, or Discarded
- **Signal Type**: True Signal or Not Signal (based on risk evaluation)
- **Countries**: Extracted affected countries
- **Hazard Types**: Identified hazard types using Sendai Framework
- **Risk Scores**: Vulnerability score, Coping score, and Total risk score
- **Risk Assessment**: Detailed AI evaluation text
- **Metadata**: Signal ID and processing timestamp

## Technical Details

### Architecture

- **Backend**: Flask application with SQLite database
- **Frontend**: HTML/CSS/JavaScript with Tailwind CSS
- **AI Integration**: OpenAI GPT-4 for signal evaluation
- **EIOS Integration**: Direct API integration with WHO EIOS system
- **Scheduling**: Background threading for hourly processing

### Database Schema

- **RawSignal**: Stores original signal data from EIOS
- **ProcessedSignal**: Stores AI-evaluated signals with extracted information
- **UserConfig**: Stores user configuration (tags)
- **ProcessedSignalID**: Tracks processed signals to avoid reprocessing

### API Endpoints

- `POST /api/signals/fetch`: Trigger manual signal fetching
- `GET /api/signals/processed`: Retrieve processed signals
- `GET/POST /api/signals/tags`: Manage EIOS tags
- `POST /api/signals/{id}/flag`: Flag a signal
- `POST /api/signals/{id}/discard`: Discard a signal
- `POST /api/signals/batch-action`: Batch flag/discard operations
- `POST /api/scheduler/start`: Start automatic scheduling
- `POST /api/scheduler/stop`: Stop automatic scheduling
- `GET /api/scheduler/status`: Get scheduler status

## Risk Evaluation System

The application uses a risk scoring system based on vulnerability and coping factors:

### Vulnerability Factors (each scores -1 if present):
- Human population affected
- Fourfold increase or greater from usual seasonal pattern
- Unknown etiology
- New public health signal or event
- Localized event/single case of mild disease (0 points)
- Endemic but 2-fold higher than usual level
- Threat to health system
- Occurs in conflict area

### Coping Factors:
- Scored from 0 (not adequate) to 7 (fully adequate)

### Signal Determination:
- Total score = Vulnerability score + Coping score
- If total score is between -7 and 0 (inclusive): **Signal**
- If total score is positive: **Not Signal**

## Troubleshooting

1. **Connection Errors**: Ensure EIOS API credentials are correct
2. **OpenAI API Errors**: Check API key and rate limits
3. **Database Issues**: Delete `src/database/app.db` to reset database
4. **Port Conflicts**: Change port in `src/main.py` if 5000 is occupied

## Dependencies

- Flask: Web framework
- SQLAlchemy: Database ORM
- Requests: HTTP client for API calls
- Flask-CORS: Cross-origin resource sharing
- python-dotenv: Environment variable management

## Security Notes

- The application includes CORS enabled for development
- API keys are stored in `.env` file
- Database is SQLite for simplicity
- For production deployment, consider using PostgreSQL and proper secret management

