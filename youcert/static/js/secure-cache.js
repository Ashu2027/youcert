/**
 * YOUCERT SECURE LOCAL STORAGE CACHE
 * Prevents cache bleeding between users and pages
 * User-specific and session-specific caching
 */

(function() {
    'use strict';

    // ===================== SECURE CACHE MANAGER =====================
    class SecureCache {
        constructor() {
            this.prefix = 'youcert_cache_';
            this.userKey = null;
            this.sessionKey = null;
            this.initialized = false;
        }

        /**
         * Initialize cache with user-specific key
         * Prevents cache bleeding between users
         */
        init(userId = null, sessionId = null) {
            // Get user ID from meta tag or parameter
            if (!userId) {
                const userMeta = document.querySelector('meta[name="user-id"]');
                userId = userMeta ? userMeta.getAttribute('content') : null;
            }

            // Get session ID from meta tag or parameter
            if (!sessionId) {
                const sessionMeta = document.querySelector('meta[name="session-id"]');
                sessionId = sessionMeta ? sessionMeta.getAttribute('content') : null;
            }

            // If no user ID, generate anonymous session ID
            if (!userId) {
                userId = 'anonymous_' + this.generateSessionId();
            }

            // Create user-specific key
            this.userKey = this.hashString(userId);
            this.sessionKey = sessionId || this.generateSessionId();
            this.initialized = true;

            // Clean up old cache entries on init
            this.cleanupExpired();
            this.cleanupOtherUsers();
        }

        /**
         * Generate session-specific ID
         */
        generateSessionId() {
            return 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        }

        /**
         * Simple hash function for user ID
         */
        hashString(str) {
            let hash = 0;
            for (let i = 0; i < str.length; i++) {
                const char = str.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash = hash & hash;
            }
            return 'u_' + Math.abs(hash).toString(36);
        }

        /**
         * Get full cache key with user prefix
         */
        getCacheKey(key) {
            if (!this.initialized) {
                console.warn('SecureCache not initialized. Call init() first.');
                return null;
            }
            return `${this.prefix}${this.userKey}_${key}`;
        }

        /**
         * Set item in cache with expiration
         * @param {string} key - Cache key
         * @param {any} value - Value to cache
         * @param {number} ttl - Time to live in seconds (default: 5 minutes)
         */
        set(key, value, ttl = 300) {
            const cacheKey = this.getCacheKey(key);
            if (!cacheKey) return false;

            try {
                const cacheData = {
                    value: value,
                    expiry: Date.now() + (ttl * 1000),
                    userId: this.userKey,
                    sessionId: this.sessionKey,
                    timestamp: Date.now()
                };

                localStorage.setItem(cacheKey, JSON.stringify(cacheData));
                return true;
            } catch (e) {
                console.error('Cache set error:', e);
                // If storage is full, clear old entries
                if (e.name === 'QuotaExceededError') {
                    this.clearOldest(5);
                    try {
                        localStorage.setItem(cacheKey, JSON.stringify({
                            value: value,
                            expiry: Date.now() + (ttl * 1000),
                            userId: this.userKey,
                            sessionId: this.sessionKey,
                            timestamp: Date.now()
                        }));
                        return true;
                    } catch (e2) {
                        return false;
                    }
                }
                return false;
            }
        }

        /**
         * Get item from cache
         * @param {string} key - Cache key
         * @returns {any|null} - Cached value or null if not found/expired
         */
        get(key) {
            const cacheKey = this.getCacheKey(key);
            if (!cacheKey) return null;

            try {
                const cached = localStorage.getItem(cacheKey);
                if (!cached) return null;

                const cacheData = JSON.parse(cached);

                // Security: Verify user match (prevent cache bleeding)
                if (cacheData.userId !== this.userKey) {
                    console.warn('Cache user mismatch - clearing');
                    localStorage.removeItem(cacheKey);
                    return null;
                }

                // Check expiration
                if (Date.now() > cacheData.expiry) {
                    localStorage.removeItem(cacheKey);
                    return null;
                }

                return cacheData.value;
            } catch (e) {
                console.error('Cache get error:', e);
                return null;
            }
        }

        /**
         * Check if key exists and is valid
         */
        has(key) {
            return this.get(key) !== null;
        }

        /**
         * Remove specific cache entry
         */
        remove(key) {
            const cacheKey = this.getCacheKey(key);
            if (!cacheKey) return false;

            try {
                localStorage.removeItem(cacheKey);
                return true;
            } catch (e) {
                console.error('Cache remove error:', e);
                return false;
            }
        }

        /**
         * Clear all cache for current user
         */
        clear() {
            if (!this.initialized) return false;

            try {
                const keysToRemove = [];
                const userPrefix = `${this.prefix}${this.userKey}_`;

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(userPrefix)) {
                        keysToRemove.push(key);
                    }
                }

                keysToRemove.forEach(key => localStorage.removeItem(key));
                return true;
            } catch (e) {
                console.error('Cache clear error:', e);
                return false;
            }
        }

        /**
         * Clear all expired entries
         */
        cleanupExpired() {
            try {
                const keysToRemove = [];
                const now = Date.now();

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(this.prefix)) {
                        try {
                            const data = JSON.parse(localStorage.getItem(key));
                            if (data && data.expiry && now > data.expiry) {
                                keysToRemove.push(key);
                            }
                        } catch (e) {
                            // Invalid data, remove it
                            keysToRemove.push(key);
                        }
                    }
                }

                keysToRemove.forEach(key => localStorage.removeItem(key));
            } catch (e) {
                console.error('Cache cleanup error:', e);
            }
        }

        /**
         * Clear cache entries from other users (security measure)
         */
        cleanupOtherUsers() {
            if (!this.initialized) return;

            try {
                const keysToRemove = [];
                const currentUserPrefix = `${this.prefix}${this.userKey}_`;

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(this.prefix) && !key.startsWith(currentUserPrefix)) {
                        keysToRemove.push(key);
                    }
                }

                keysToRemove.forEach(key => localStorage.removeItem(key));
            } catch (e) {
                console.error('Cache cleanup other users error:', e);
            }
        }

        /**
         * Clear oldest N entries when storage is full
         */
        clearOldest(count = 5) {
            try {
                const cacheEntries = [];
                const userPrefix = `${this.prefix}${this.userKey}_`;

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(userPrefix)) {
                        try {
                            const data = JSON.parse(localStorage.getItem(key));
                            if (data && data.timestamp) {
                                cacheEntries.push({ key, timestamp: data.timestamp });
                            }
                        } catch (e) {
                            // Invalid entry, add to removal list
                            cacheEntries.push({ key, timestamp: 0 });
                        }
                    }
                }

                // Sort by timestamp (oldest first)
                cacheEntries.sort((a, b) => a.timestamp - b.timestamp);

                // Remove oldest entries
                for (let i = 0; i < Math.min(count, cacheEntries.length); i++) {
                    localStorage.removeItem(cacheEntries[i].key);
                }
            } catch (e) {
                console.error('Clear oldest error:', e);
            }
        }

        /**
         * Get cache statistics
         */
        getStats() {
            if (!this.initialized) return null;

            try {
                let totalEntries = 0;
                let totalSize = 0;
                let expiredCount = 0;
                const userPrefix = `${this.prefix}${this.userKey}_`;
                const now = Date.now();

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(userPrefix)) {
                        totalEntries++;
                        const value = localStorage.getItem(key);
                        totalSize += value ? value.length : 0;

                        try {
                            const data = JSON.parse(value);
                            if (data && data.expiry && now > data.expiry) {
                                expiredCount++;
                            }
                        } catch (e) {
                            // Ignore parse errors
                        }
                    }
                }

                return {
                    entries: totalEntries,
                    sizeBytes: totalSize,
                    sizeKB: (totalSize / 1024).toFixed(2),
                    expired: expiredCount,
                    userId: this.userKey
                };
            } catch (e) {
                console.error('Get stats error:', e);
                return null;
            }
        }

        /**
         * Cached AJAX request
         * @param {string} url - Request URL
         * @param {object} options - Fetch options
         * @param {number} ttl - Cache TTL in seconds
         * @returns {Promise} - Fetch promise
         */
        async cachedFetch(url, options = {}, ttl = 300) {
            const cacheKey = 'fetch_' + this.hashString(url + JSON.stringify(options));

            // Check cache first
            const cached = this.get(cacheKey);
            if (cached) {
                return Promise.resolve(cached);
            }

            // Fetch from server
            try {
                const response = await fetch(url, options);
                const data = await response.json();

                // Cache successful responses only
                if (response.ok) {
                    this.set(cacheKey, data, ttl);
                }

                return data;
            } catch (error) {
                throw error;
            }
        }

        /**
         * Invalidate cache entries matching pattern
         */
        invalidatePattern(pattern) {
            if (!this.initialized) return false;

            try {
                const keysToRemove = [];
                const userPrefix = `${this.prefix}${this.userKey}_`;

                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.startsWith(userPrefix) && key.includes(pattern)) {
                        keysToRemove.push(key);
                    }
                }

                keysToRemove.forEach(key => localStorage.removeItem(key));
                return true;
            } catch (e) {
                console.error('Invalidate pattern error:', e);
                return false;
            }
        }
    }

    // ===================== GLOBAL INSTANCE =====================
    window.SecureCache = new SecureCache();

    // Auto-initialize on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.SecureCache.init();
        });
    } else {
        window.SecureCache.init();
    }

    // Clear cache on logout
    window.addEventListener('beforeunload', function() {
        const isLogout = window.location.pathname.includes('/logout');
        if (isLogout && window.SecureCache) {
            window.SecureCache.clear();
        }
    });

})();
