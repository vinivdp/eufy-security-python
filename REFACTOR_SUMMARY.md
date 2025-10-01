# Major Refactor Summary - Motion Detection with Polling-Based Health Monitoring

## ✅ Completed (Parts 1 & 2)

### New Architecture

**Camera Registry System**
- CSV file: `config/cameras.txt` with columns: `Camera_SN,Slack_channel,latest_activity,state`
- In-memory registry loaded on startup
- Thread-safe read/write operations
- Persists state changes back to CSV

**Motion Detection State Machine**
- `CLOSED + Motion` → `OPEN` + Send webhook
- `OPEN + Motion` → Send webhook (no state change)
- `OPEN + 1hr timeout` → `CLOSED` + Send motion_stopped webhook
- No automatic snoozing
- All webhooks include: device_sn, slack_channel, state, latest_activity

**Polling-Based Health Monitoring**
- Runs every 5 minutes for all registered cameras
- Battery check: Alert if level < 30% (cooldown: 24hrs per camera)
- Offline check: Alert after 3 consecutive failures with exponential backoff
- Uses `device.get_properties` command with `["battery"]` property

**State Timeout Checker**
- Background task runs every 1 minute
- Auto-closes cameras with `latest_activity` > 1 hour ago
- Sends motion_stopped webhook on auto-close

**Timezone**
- All timestamps use Brasília timezone (America/Sao_Paulo, UTC-3)
- ISO 8601 format: `2025-10-01T11:07:11.539-03:00`

### Files Created
- `src/services/camera_registry.py` - Camera registry with CSV persistence
- `src/services/state_timeout_checker.py` - Auto-close cameras after timeout
- `config/cameras.txt` - Sample camera list (28 cameras)

### Files Modified
- `src/orchestrator.py` - Completely rewritten for new architecture
- `src/handlers/motion_handler.py` - Simplified to state machine only
- `src/services/device_health_checker.py` - Rewritten for polling-based monitoring
- `src/models/events.py` - Added slack_channel, Brasília timezone, state tracking
- `src/utils/config.py` - Added MotionConfig, updated OfflineAlertConfig
- `src/services/__init__.py` - Added new service exports
- `src/handlers/__init__.py` - Deprecated offline/battery handlers

### Event Listeners
**REMOVED (no longer listening):**
- ❌ `disconnected` / `device removed`
- ❌ `connected` / `device added`
- ❌ `property changed` (snapshots/pictures)
- ❌ `low battery` (now polling-based)
- ❌ `livestream video data` / `audio data`

**KEPT:**
- ✅ `motion detected` (ONLY event listener)

### Webhook Payloads

**Motion Detected**
```json
{
  "event": "motion_detected",
  "device_sn": "T8B005112336016A",
  "slack_channel": "condominio-lemonde",
  "state": "open",
  "latest_activity": "2025-10-01T11:07:11.539-03:00",
  "timestamp": "2025-10-01T11:07:11.539-03:00",
  "device_name": "Front Door Camera",
  "event_type": "motion_detected",
  "raw_event": {...}
}
```

**Motion Stopped (timeout)**
```json
{
  "event": "motion_stopped",
  "device_sn": "T8B005112336016A",
  "slack_channel": "condominio-lemonde",
  "state": "closed",
  "duration_seconds": 3600,
  "latest_activity": "2025-10-01T11:07:11.539-03:00",
  "timestamp": "2025-10-01T12:07:11.539-03:00"
}
```

**Low Battery (polling)**
```json
{
  "event": "low_battery",
  "device_sn": "T8B005112336016A",
  "slack_channel": "condominio-lemonde",
  "battery_level": 25,
  "timestamp": "2025-10-01T11:07:11.539-03:00"
}
```

**Camera Offline (polling)**
```json
{
  "event": "camera_offline",
  "device_sn": "T8B005112336016A",
  "slack_channel": "condominio-lemonde",
  "reason": "health_check_failed",
  "timestamp": "2025-10-01T11:07:11.539-03:00"
}
```

### Configuration

**New Settings**
```python
class MotionConfig:
    state_timeout_minutes: int = 60  # 1 hour

class OfflineAlertConfig:
    polling_interval_minutes: int = 5
    failure_threshold: int = 3
    battery_threshold_percent: int = 30  # integer 0-100
```

## ⏳ TODO (Part 3)

### Testing
- [ ] Update all tests to match new architecture
- [ ] Test camera registry CRUD operations
- [ ] Test motion state machine transitions
- [ ] Test timeout checker
- [ ] Test health checker polling
- [ ] Mock Brasília timezone in tests

### Deprecation Cleanup (Optional)
- [ ] Move `offline_handler.py` to deprecated folder
- [ ] Move `battery_handler.py` to deprecated folder
- [ ] Update test fixtures to remove deprecated mocks

### Documentation
- [ ] Update README with new architecture
- [ ] Document camera registry CSV format
- [ ] Document webhook payload schemas
- [ ] Add deployment guide for Render

### Deployment
- [ ] Test locally with real eufy-security-ws instance
- [ ] Update `config/cameras.txt` with real production data
- [ ] Deploy to Render
- [ ] Monitor logs for first 24 hours

## Breaking Changes

1. **Camera Registry Required**: System won't start without `config/cameras.txt`
2. **Webhook Payload Changes**: All webhooks now include `slack_channel` and `state`
3. **Timezone Changes**: All timestamps now in Brasília time (was UTC)
4. **No Auto-Snoozing**: Removed automatic snooze after max duration
5. **Event Listeners**: Only listening to motion_detected (all others removed)

## Benefits

✅ **No False Alarms**: Polling-based offline detection eliminates sleep-related false positives
✅ **Proactive Monitoring**: Know about issues before users report them
✅ **State Tracking**: Full visibility into camera state (open/closed)
✅ **Battery Monitoring**: Automatic low battery alerts
✅ **Slack Integration**: Per-camera Slack channel routing
✅ **Timezone Accuracy**: All times in user's local timezone (Brasília)
✅ **CSV Persistence**: Camera state survives restarts

## Commits

- Part 1 (63cf83b): Core services and models
- Part 2 (274a417): Orchestrator integration and wiring
