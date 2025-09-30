# Eufy Security Python Integration

Advanced Eufy Security camera integration with Workato webhooks, continuous video recording, and intelligent event handling.

## 🎯 Features

- **Continuous Motion Recording**: Records video continuously while motion is detected (up to 15 minutes)
- **Intelligent Motion Detection**: Automatically stops recording after 60 seconds of no motion
- **Public Video URLs**: Generates instant public URLs for video recordings served via HTTP
- **Multiple Event Handlers**:
  - Motion detection (start/stop)
  - Low battery alerts
  - Camera offline detection
- **Error Reporting**: Failed operations are logged and reported to Workato
- **90-Day Retention**: Automatic cleanup of old recordings
- **3x Retry Logic**: All operations retry 3 times with exponential backoff
- **FastAPI REST API**: Full API for monitoring and management

## 📋 Prerequisites

- Python 3.11+
- Poetry (for dependency management)
- Docker & Docker Compose (for containerized deployment)
- eufy-security-ws server running
- Workato webhook URL

## 🚀 Quick Start

### Local Development

1. **Clone the repository**
   ```bash
   cd /path/to/eufy-security-python
   ```

2. **Install dependencies**
   ```bash
   make install
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

4. **Run locally**
   ```bash
   make run
   ```

### Docker Deployment

1. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. **Start services**
   ```bash
   make docker-run
   ```

3. **View logs**
   ```bash
   make docker-logs
   ```

## 🔧 Configuration

Edit `config/config.yaml`:

```yaml
server:
  host: "0.0.0.0"
  port: 10000
  public_url: "https://your-app.onrender.com"

recording:
  max_duration_seconds: 900    # 15 minutes
  motion_timeout_seconds: 60   # Stop after 60s no motion
  snooze_duration_seconds: 3600  # 1 hour
  retention_days: 90

workato:
  webhook_url: "https://webhooks.workato.com/..."

retry:
  max_attempts: 3
  initial_delay: 1.0
  backoff_multiplier: 2.0
```

## 📡 API Endpoints

### Health Check
```bash
GET /health
```

### Serve Video Recording
```bash
GET /recordings/{filename}
```

### List Recordings
```bash
GET /recordings?limit=50
```

### Storage Statistics
```bash
GET /storage
```

### Device Status
```bash
GET /devices
```

### Recent Errors
```bash
GET /errors?limit=10
```

### Manual Cleanup
```bash
POST /cleanup
```

### API Documentation
- Swagger UI: `http://localhost:10000/docs`
- ReDoc: `http://localhost:10000/redoc`

## 🎬 Workflow

### Motion Detection
```
1. Motion detected event received
   ↓
2. Start video recording
   ↓
3. Generate public URL: https://app.onrender.com/recordings/{device_sn}_{timestamp}.mp4
   ↓
4. Send webhook to Workato:
   {
     "event": "motion_detected",
     "device_sn": "T8600P23232...",
     "video_url": "https://...",
     "video_status": "recording"
   }
   ↓
5. Continue recording while motion detected
   ↓
6. [60s no motion OR 15min max reached]
   ↓
7. Stop recording
   ↓
8. Send webhook to Workato:
   {
     "event": "motion_stopped",
     "device_sn": "T8600P23232...",
     "video_url": "https://...",
     "video_status": "completed",
     "duration_seconds": 323
   }
```

### Low Battery
```
1. Low battery event received
   ↓
2. Check cooldown (24 hours)
   ↓
3. Send webhook to Workato:
   {
     "event": "low_battery",
     "device_sn": "T8600P23232...",
     "battery_level": 15
   }
```

### Camera Offline
```
1. Disconnect event received
   ↓
2. Wait 30 seconds (debounce)
   ↓
3. If still offline, send webhook:
   {
     "event": "camera_offline",
     "device_sn": "T8600P23232...",
     "reason": "disconnected"
   }
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│           FastAPI Application               │
│  ┌────────────┐  ┌──────────────────────┐   │
│  │  Routes    │  │  EventOrchestrator   │   │
│  │  /health   │  │                      │   │
│  │  /recordings│ │  ┌──────────────┐   │   │
│  └────────────┘  │  │  Handlers    │   │   │
│                  │  │  - Motion    │   │   │
│                  │  │  - Offline   │   │   │
│                  │  │  - Battery   │   │   │
│                  │  └──────────────┘   │   │
│                  │                      │   │
│                  │  ┌──────────────┐   │   │
│                  │  │  Services    │   │   │
│                  │  │  - VideoRec  │   │   │
│                  │  │  - Workato   │   │   │
│                  │  │  - Storage   │   │   │
│                  │  │  - ErrorLog  │   │   │
│                  │  └──────────────┘   │   │
│                  └──────────────────────┘   │
│                           ↕                  │
│                  ┌──────────────────────┐   │
│                  │  WebSocketClient     │   │
│                  └──────────────────────┘   │
└─────────────────────────────────────────────┘
                           ↕
               eufy-security-ws (port 3000)
                           ↕
                  Eufy Security Cloud
```

## 🧪 Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Lint code
make lint

# Format code
make format
```

## 📊 Storage Management

- **Retention**: 90 days (configurable)
- **Cleanup Schedule**: Daily at 3 AM
- **Manual Cleanup**: `POST /cleanup`
- **Disk Space Monitoring**: Automatic cleanup when space is low

### Storage Requirements

- **Per Recording**: ~75-150 MB (5-10 minutes)
- **Per Camera Per Day**: ~750 MB - 1.5 GB (10 recordings)
- **90 Days (2 cameras)**: ~135-270 GB

**Recommended**: 150 GB disk on Render

## 🚢 Deployment to Render

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/eufy-security-python.git
   git push -u origin main
   ```

2. **Connect to Render**
   - Go to [render.com](https://render.com)
   - Create New → Web Service
   - Connect your GitHub repository
   - Render will auto-detect `render.yaml`

3. **Set Environment Variables**
   - `WORKATO_WEBHOOK_URL`
   - `EUFY_USERNAME`
   - `EUFY_PASSWORD`

4. **Deploy**
   - Render will build and deploy automatically
   - Access your app at: `https://your-app.onrender.com`

## 💰 Cost Estimate (Render)

- **Starter Plan**: $7/month
- **150GB Disk**: $35/month (140GB × $0.25/GB)
- **Total**: ~$42/month

## 🔒 Security

- Non-root Docker container
- Environment variable-based secrets
- No hardcoded credentials
- HTTPS only (via Render)
- Video URLs are public but unguessable (can add signed URLs)

## 📝 Event Types

| Event | Trigger | Cooldown | Retry |
|-------|---------|----------|-------|
| `motion_detected` | Motion starts | None | 3x |
| `motion_stopped` | 60s no motion OR 15min | None | 3x |
| `low_battery` | Battery < threshold | 24 hours | 3x |
| `camera_offline` | Disconnect | 30s debounce | 3x |
| `system_error` | Any failure after 3 retries | None | Best effort |

## 🐛 Troubleshooting

### WebSocket Connection Failed
```bash
# Check eufy-security-ws is running
curl http://localhost:3000/health

# Check logs
make docker-logs
```

### Video Recording Not Starting
```bash
# Check ffmpeg is installed
docker exec eufy-python which ffmpeg

# Check storage permissions
docker exec eufy-python ls -la /mnt/recordings
```

### Webhook Failures
```bash
# View recent errors
curl http://localhost:10000/errors

# Check error logs
tail -f logs/eufy-security.log
```

## 📚 Development

```bash
# Install dev dependencies
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black src tests

# Lint
poetry run ruff check src

# Type check
poetry run mypy src
```

## 🔄 Migration from Old Version

1. Deploy new version in parallel (different service name)
2. Monitor for 1 week
3. Compare webhooks and recordings
4. If successful, deprecate old version
5. Update Workato recipes to use new webhook format

## 📄 License

ISC

## 👤 Author

Vinicius van der Put

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/eufy-security-python/issues)
- **Docs**: See `/docs` endpoint when running

---

**Version**: 2.0.0
**Python**: 3.11+
**Framework**: FastAPI
**Deployment**: Docker / Render