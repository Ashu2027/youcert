# Deploying Youcert to Cloudflare

> **License Notice**: Individual content creators (e.g., YouTubers, educators) are granted a free license to self-host and modify this software exclusively for their own personal audience and learners. However, no entity may host, distribute, or offer this software as a service (SaaS) to third-party creators, nor use it to build a competing commercial platform without explicit written permission. If you are a business entity interested in commercial usage, please contact me directly at ashutoshbhunia01@gmail.com.

Youcert is built using Cloudflare's **Containers** architecture, allowing you to run a full Python Flask + Gunicorn/Gevent backend directly on Cloudflare's edge network. This guide covers how to deploy the application along with its required services (R2, Queues, and Secrets).

## Prerequisites

1. **Cloudflare Account**: A Cloudflare account with a configured zone (domain).
2. **Docker**: You must have Docker (or Docker Desktop) installed and running locally, as Wrangler will use it to build the container image.
3. **Node.js & Wrangler**: Install Cloudflare Wrangler CLI.
   ```bash
   npm install -g wrangler
   wrangler login
   ```

## 1. Create Required Cloudflare Services

Before deploying the container, you need to set up the necessary Cloudflare infrastructure that the app binds to in `wrangler.toml`.

### A. R2 Storage Bucket
The application uses Cloudflare R2 to store generated certificates, uploaded videos, and assets.
```bash
wrangler r2 bucket create lumsas-buc-main
```
*(Note: If you change the bucket name, ensure you update it in `wrangler.toml` under `[[r2_buckets]]` and in your `.env` as `R2_BUCKET_NAME`)*

### B. Cloudflare Queues
Youcert relies on Cloudflare Queues for asynchronous background jobs like video chunking and AI processing.
```bash
wrangler queues create video-processing-queue
wrangler queues create chunk-generation-queue
```

## 2. Configure Secrets

Cloudflare Containers do not read from your local `.env` file in production. Instead, you must securely upload your production secrets using Wrangler. 

Run the following commands and paste the respective values from your TiDB, Google, Razorpay, and ZeptoMail dashboards:

```bash
wrangler secret put SECRET_KEY
wrangler secret put TOKEN_ENCRYPTION_KEY
wrangler secret put MYSQL_HOST
wrangler secret put MYSQL_USER
wrangler secret put MYSQL_PASSWORD
wrangler secret put GOOGLE_CLIENT_ID
wrangler secret put GOOGLE_CLIENT_SECRET
wrangler secret put RAZORPAY_KEY_ID
wrangler secret put RAZORPAY_KEY_SECRET
wrangler secret put ZEPTOMAIL_TOKEN
```

*Tip: For a complete list of required environment variables, refer to the `.env.example` file in the root directory.*

## 3. Review `wrangler.toml`

Ensure that your `wrangler.toml` file correctly maps your custom domain routes. By default, it expects:
```toml
[[routes]]
pattern = "youcert.com/*"
zone_name = "youcert.com"
```
Update `zone_name` and `pattern` to match your actual domain registered in Cloudflare.

## 4. Deploy

With Docker running in the background and all secrets configured, you can deploy the application:

```bash
wrangler deploy
```

### What happens during deployment?
1. **Local Build**: Wrangler uses your local Docker daemon to build the `Dockerfile` into a container image containing Python 3.10, Flask, and your code.
2. **Push**: The image is automatically uploaded to your Cloudflare account's private container registry.
3. **Deploy**: Cloudflare spins up container instances backed by Durable Objects to serve your application securely from the edge.

## 5. View Logs & Debugging

If you need to view live application logs or trace errors in production:
```bash
wrangler tail
```
*(Ensure `[observability] enabled = true` is set in your `wrangler.toml`)*
