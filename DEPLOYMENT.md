# Deployment Guide

## 🚀 Deploying to Render

### Step 1: Prepare Repository

1. **Initialize Git** (if not already done)
   ```bash
   cd /path/to/eufy-security-python
   git init
   git add .
   git commit -m "Initial commit: Eufy Security Python v2.0"
   ```

2. **Create GitHub Repository**
   - Go to [github.com](https://github.com)
   - Create a new repository: `eufy-security-python`
   - Don't initialize with README (we already have one)

3. **Push to GitHub**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/eufy-security-python.git
   git branch -M main
   git push -u origin main
   ```

### Step 2: Deploy to Render

1. **Create Render Account**
   - Go to [render.com](https://render.com)
   - Sign up or log in

2. **Create New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub account
   - Select `eufy-security-python` repository
   - Render will automatically detect `render.yaml`

3. **Configure Service**
   - **Name**: `eufy-security-python`
   - **Region**: Choose closest to your location
   - **Branch**: `main`
   - **Plan**: Starter ($7/month minimum)

4. **Add Persistent Disk**
   - In the service settings, go to "Disks"
   - Click "Add Disk"
   - **Name**: `recordings`
   - **Mount Path**: `/mnt/recordings`
   - **Size**: 150 GB
   - Click "Save"

5. **Set Environment Variables**

   Go to "Environment" tab and add:

   ```
   WORKATO_WEBHOOK_URL = https://webhooks.workato.com/webhooks/rest/YOUR_ID/eufy
   EUFY_USERNAME = your_email@example.com
   EUFY_PASSWORD = your_password
   EUFY_WS_URL = ws://127.0.0.1:3000/ws
   LOG_LEVEL = INFO
   PYTHONUNBUFFERED = 1
   ```

6. **Deploy**
   - Click "Create Web Service"
   - Render will build and deploy automatically
   - Wait 5-10 minutes for first deployment

### Step 3: Verify Deployment

1. **Check Health Endpoint**
   ```bash
   curl https://your-app.onrender.com/health
   ```

2. **Check Logs**
   - In Render dashboard, go to "Logs" tab
   - Look for "✅ Application started successfully"

3. **Test API Docs**
   - Visit: `https://your-app.onrender.com/docs`
   - You should see Swagger UI

### Step 4: Configure eufy-security-ws

Since Render doesn't support multi-container deployments via `render.yaml`, you need to run `eufy-security-ws` separately:

**Option A: Run on Same Service (Recommended)**

Modify `Dockerfile` to run both services:

```dockerfile
# Add to Dockerfile before CMD
# Install Node.js
RUN apt-get update && apt-get install -y nodejs npm

# Install eufy-security-ws
RUN npm install -g eufy-security-ws

# Create startup script
RUN echo '#!/bin/bash\neufy-security-server -H 0.0.0.0 &\nsleep 5\npython -m uvicorn src.main:app --host 0.0.0.0 --port 10000' > /app/start.sh
RUN chmod +x /app/start.sh

# Change CMD to
CMD ["/app/start.sh"]
```

**Option B: Separate Service**

Create a second Render service for `eufy-security-ws`:
1. Create new "Private Service" in Render
2. Use Docker image: `bropat/eufy-security-ws:latest`
3. Set internal URL in Python service: `ws://eufy-security-ws:3000/ws`

## 🐳 Local Docker Testing

### Before Deployment

Test locally with Docker Compose:

```bash
# 1. Copy environment file
cp .env.example .env

# 2. Edit .env with your credentials
nano .env

# 3. Build and run
make docker-run

# 4. Check logs
make docker-logs

# 5. Test locally
curl http://localhost:10000/health

# 6. Stop when done
make docker-stop
```

## 🔄 Continuous Deployment

Render automatically deploys on every push to `main` branch:

```bash
# Make changes
git add .
git commit -m "Update: description"
git push origin main

# Render will automatically:
# 1. Detect changes
# 2. Build new Docker image
# 3. Deploy with zero downtime
```

## 📊 Monitoring

### Health Checks

Render automatically monitors `/health` endpoint:
- **Healthy**: Returns 200 status
- **Unhealthy**: Render restarts service automatically

### Logs

View logs in Render dashboard or via CLI:

```bash
# Install Render CLI
npm install -g @render-com/cli

# Login
render login

# View logs
render logs -f your-service-id
```

### Metrics

Monitor in Render dashboard:
- CPU usage
- Memory usage
- Request rate
- Response time

## 🔐 Security Checklist

- [ ] Environment variables set (not in code)
- [ ] HTTPS enabled (automatic on Render)
- [ ] Non-root Docker user
- [ ] Health checks configured
- [ ] Log file rotation enabled
- [ ] Disk space monitoring active

## 💰 Cost Breakdown

| Item | Cost |
|------|------|
| Starter Plan | $7/month |
| 150GB Disk | $35/month |
| **Total** | **$42/month** |

To reduce costs:
- Use smaller disk (50GB = $10/month extra)
- Reduce retention to 30 days
- Use instance plan (more resources)

## 🆘 Troubleshooting

### Build Fails

Check `Dockerfile` syntax:
```bash
docker build -t test .
```

### Service Doesn't Start

Check environment variables:
```bash
render env list your-service-id
```

### WebSocket Connection Fails

Verify `eufy-security-ws` is running:
```bash
curl http://localhost:3000/health
```

### Out of Disk Space

Trigger manual cleanup:
```bash
curl -X POST https://your-app.onrender.com/cleanup
```

Or increase disk size in Render dashboard.

## 📞 Support

- **Render Docs**: https://render.com/docs
- **Render Community**: https://community.render.com
- **Project Issues**: https://github.com/YOUR_USERNAME/eufy-security-python/issues

---

**Next Steps**: After deployment, update your Workato recipes to use the new webhook format and video URLs!