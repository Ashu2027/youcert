/**
 * worker.js — Cloudflare Containers Worker Entry Point for YOUCERT
 *
 * Thin proxy Worker. All application logic lives in the Flask container.
 * Uses the official @cloudflare/containers Container class API.
 *
 * Docs: https://developers.cloudflare.com/containers/container-package
 *
 * Architecture:
 *   Internet → Cloudflare Worker (this file) → Flask Container (Dockerfile)
 */

import { Container } from "@cloudflare/containers";

/**
 * YoucertContainer — defines the container configuration.
 * class_name must match [[containers]] class_name in wrangler.toml.
 *
 * Docs: https://developers.cloudflare.com/containers/container-package
 */
export class YoucertContainer extends Container {
    /** Port that gunicorn listens on inside the container */
    defaultPort = 8080;

    /**
     * Stop idle container instance after 2 minutes of no requests.
     * Next request will cold-start a new instance (wsgi.py handles it fast).
     */
    sleepAfter = "2m";

    /**
     * Set up explicitly passed environment variables
     * We MUST specify them by exact name as they arrive from Cloudflare Secrets.
     * Doing this in the constructor guarantees they are populated before start().
     */
    constructor(ctx, env) {
        super(ctx, env);
        this.envVars = {
            // ── Core environment toggle (single source of truth) ──────────────
            IS_DEVELOPMENT: env.IS_DEVELOPMENT || "false",
            PORT: "8080",

            // ── Database (TiDB Cloud Serverless) ──────────────────────────────
            MYSQL_HOST: env.MYSQL_HOST || "",
            MYSQL_USER: env.MYSQL_USER || "",
            MYSQL_PASSWORD: env.MYSQL_PASSWORD || "",
            MYSQL_PORT: env.MYSQL_PORT || "4000",

            // ── API Keys & Secrets ────────────────────────────────────────────
            SECRET_KEY: env.SECRET_KEY || "",
            TOKEN_ENCRYPTION_KEY: env.TOKEN_ENCRYPTION_KEY || "",
            GEMINI_API_KEY: env.GEMINI_API_KEY || "",
            GEMINI_MODEL: env.GEMINI_MODEL || "",

            // ── Google OAuth ──────────────────────────────────────────────────
            GOOGLE_CLIENT_ID: env.GOOGLE_CLIENT_ID || "",
            GOOGLE_CLIENT_SECRET: env.GOOGLE_CLIENT_SECRET || "",

            // ── Razorpay ──────────────────────────────────────────────────────
            RAZORPAY_KEY_ID: env.RAZORPAY_KEY_ID || "",
            RAZORPAY_KEY_SECRET: env.RAZORPAY_KEY_SECRET || "",

            // ── ZeptoMail ─────────────────────────────────────────────────────
            ZEPTOMAIL_TOKEN: env.ZEPTOMAIL_TOKEN || "",

            // ── Cloudflare R2 Storage ─────────────────────────────────────────
            CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID || "",
            CLOUDFLARE_API_TOKEN: env.CLOUDFLARE_API_TOKEN || "",
            R2_BUCKET_NAME: env.R2_BUCKET_NAME || "",
            R2_ENDPOINT_URL: env.R2_ENDPOINT_URL || "",
            R2_ACCESS_KEY_ID: env.R2_ACCESS_KEY_ID || "",
            R2_SECRET_ACCESS_KEY: env.R2_SECRET_ACCESS_KEY || "",
            R2_PUBLIC_URL: env.R2_PUBLIC_URL || "",

            // ── Background Queues ─────────────────────────────────────────────
            VIDEO_PROCESSING_QUEUE_ID: env.VIDEO_PROCESSING_QUEUE_ID || "",
            CHUNK_GENERATION_QUEUE_ID: env.CHUNK_GENERATION_QUEUE_ID || ""
        };
    }

    /** Hook called when container starts successfully */
    onStart() {
        console.log("[YoucertContainer] Container started successfully");
    }

    /** Hook called when container stops */
    onStop() {
        console.log("[YoucertContainer] Container stopped");
    }

    /** Hook called on container error */
    onError(error) {
        console.log("[YoucertContainer] Container error:", error);
    }

    /**
     * Intercept requests to the container to add admin controls
     * Since Durable Objects live permanently, we need a way to force a cold boot
     * to pick up new secrets or environment variables.
     */
    async fetch(request) {
        const url = new URL(request.url);
        if (url.pathname === "/_kill") {
            await this.destroy();
            const client_id = this.env.GOOGLE_CLIENT_ID || "SECRET_IS_BLANK";
            return new Response(`Container destroyed. Client ID in Worker: ${client_id}`, { status: 200 });
        }

        // Forward all other requests to the internal Docker container
        return super.fetch(request);
    }
}

/**
 * Main Worker — receives all HTTP requests and proxies them to the container.
 *
 * Uses a single shared instance "main" — all users go to the same container.
 * For horizontal scaling, use different instance names per user/session.
 */
export default {
    /**
     * @param {Request} request
     * @param {Object} env - env.YOUCERT_APP is the Durable Object binding
     */
    async fetch(request, env) {
        // Try up to 100 containers (max_instances in wrangler.toml)
        const MAX_CONTAINERS = 100;

        for (let i = 1; i <= MAX_CONTAINERS; i++) {
            const instanceName = `container-${i}`;
            try {
                // Attempt to send request to this container
                const response = await env.YOUCERT_APP.getByName(instanceName).fetch(request);

                // If the container returns a 502/503/429, it might be overloaded.
                // We spill over to the next container.
                if (response.status === 502 || response.status === 503 || response.status === 429) {
                    console.log(`[worker] ${instanceName} is overloaded (HTTP ${response.status}). Spilling to next...`);
                    continue; // Try next instance
                }

                // Success! Return the response
                return response;

            } catch (err) {
                // If it throws a network error (container crashed or is booting and failed), spill over
                console.log(`[worker] ${instanceName} failed (${err.message}). Spilling to next...`);
                continue; // Try next instance
            }
        }

        // If we get here, ALL 100 containers are full or crashing (25,000 total concurrent users)
        console.error("[worker] All containers exhausted or unavailable.");
        return new Response(
            JSON.stringify({
                error: "System Overloaded",
                message: "YOUCERT is experiencing extreme traffic. Please try again in 30 seconds.",
            }),
            {
                status: 503,
                headers: {
                    "Content-Type": "application/json",
                    "Retry-After": "30",
                },
            }
        );
    },
};
