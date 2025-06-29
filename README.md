# FeatureVisor Pilot

**FeatureVisor Pilot** is a Redis-backed service that implements Thompson Sampling for dynamic weight optimization in [FeatureVisor](https://github.com/featurevisor/featurevisor) experiments. This service tracks variant exposures and conversions, automatically adjusting variant weights based on Bayesian statistics to optimize for the best-performing variants.

Currently, only conversion goals are supported.

## Overview

This service acts as a companion to FeatureVisor, providing:

-   Real-time tracking of variant exposures and conversions
-   Automatic weight adjustment using Thompson Sampling
-   Redis-based storage for scalability
-   RESTful API for integration
-   Scheduled recalculation of optimal weights

## How It Works

1.  **Datafile Serving**: Reads FeatureVisor datafiles and serves them from memory.
2.  **Event Tracking**: Tracks exposures and conversions for each variant.
3.  **Thompson Sampling**: Uses Bayesian statistics to calculate the probability of each variant being the best.
4.  **Weight Updates**: Automatically adjusts variant weights based on performance.
5.  **Datafile Serving**: Serves updated datafiles with optimized weights.

## Setup as FeatureVisor Submodule

### 1. Add as Submodule

In your FeatureVisor project root:

```bash
# Add the Pilot service as a submodule
git submodule add https://github.com/matan1905/featurevisor-pilot.git services/pilot

# Initialize and update the submodule
git submodule init
git submodule update
```

### 2. Configure Environment

Create a `.env` file in the submodule directory:

```bash
cd services/pilot
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=yourpassword

# Application Configuration
DATAFILES_DIR=/app/dist  # Path to built datafiles
UPDATE_INTERVAL_MINUTES=30
MIN_EXPOSURES_FOR_UPDATE=100

# Flask Configuration
HOST=0.0.0.0
PORT=5050
DEBUG=False
```

### 3. Docker Compose Setup

Add to your FeatureVisor project's `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass yourpassword
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  pilot:
    build:
      context: .
      dockerfile: ./services/pilot/Dockerfile
    ports:
      - "5050:5050"
    environment:
      - REDIS_HOST=redis
      - REDIS_PASSWORD=yourpassword
    depends_on:
      - redis
volumes:
  redis_data:
```

## API Endpoints

### Serve Datafiles

```http
GET /datafile/<path>
```

Returns the datafile with updated weights.

### Track Exposures

```http
POST /expose
Content-Type: application/json

{
  "datafile": "production/datafile.json",
  "features": {
    "checkout_button": "variant_a",
    "header_color": "blue"
  }
}
```

### Track Conversions

```http
POST /convert
Content-Type: application/json

{
  "datafile": "production/datafile.json",
  "features": {
    "checkout_button": "variant_a",
    "header_color": "blue"
  }
}
```

### Get Statistics

```http
GET /stats
GET /stats?datafile=production/datafile.json
GET /stats?datafile=production/datafile.json&feature=checkout_button
```

### Trigger Recalculation

```http
POST /recalculate
```

Manually triggers weight recalculation (useful for testing).

## Integration with FeatureVisor SDK

Update your FeatureVisor SDK initialization to use the **FeatureVisor Pilot** service:

```javascript
import { createInstance } from '@featurevisor/sdk';

const featurevisor = createInstance({
  datafileUrl: 'http://localhost:5050/datafile/production/datafile.json',
  // ... other options
});

// Track exposures
featurevisor.on('activation', (features) => {
  fetch('http://localhost:5050/expose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      datafile: 'production/datafile-tag-all.json',
      features: features
    })
  });
});

// Track conversions (example)
function trackConversion(features) {
  fetch('http://localhost:5050/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      datafile: 'production/datafile-tag-all.json',
      features: features
    })
  });
}
```


## Monitoring

### View Statistics Dashboard

Access statistics at `http://localhost:5050/stats` to see:

-   Exposure counts per variant
-   Conversion rates
-   Current weights
-   Last update timestamps

### Redis Monitoring

Connect to Redis to inspect data:

```bash
redis-cli -h localhost -a yourpassword
KEYS stats:*
HGETALL stats:production/datafile.json:checkout_button:variant_a
```


## Troubleshooting

### Service Not Updating Weights

-   Check if all variants have reached `MIN_EXPOSURES_FOR_UPDATE`.
-   Verify Redis connectivity.
-   Check logs: `docker-compose logs pilot`

### Datafiles Not Found

-   Ensure FeatureVisor build output is in the configured directory.
-   Check volume mounts in Docker.
-   Verify `DATAFILES_DIR` environment variable.

### Redis Connection Issues

-   Verify Redis is running: `docker-compose ps`
-   Check Redis password configuration.
-   Test connection: `redis-cli -h localhost -a yourpassword ping`

## License

MIT License - see LICENSE file for details.