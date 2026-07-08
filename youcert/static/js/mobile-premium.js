/**
 * YOUCERT PREMIUM MOBILE FRAMEWORK - JavaScript
 * Universal mobile interactions and responsive behaviors
 * Preserves CSRF tokens and ensures full functionality across devices
 */

(function () {
    'use strict';

    // ===================== MOBILE DETECTION =====================
    const isMobile = () => window.innerWidth <= 768;
    const isTablet = () => window.innerWidth > 768 && window.innerWidth <= 1024;
    const isTouchDevice = () => ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

    // ===================== AUTO-CREATE MOBILE NAVIGATION BAR =====================
    function createMobileNavBar() {
        if (!isMobile()) return;

        // Check if nav already exists
        const existingNav = document.querySelector('.header-nav, .navbar, .top-navbar, .mobile-nav-bar');
        if (existingNav) return;

        // Create mobile nav bar
        const mobileNav = document.createElement('div');
        mobileNav.className = 'mobile-nav-bar';

        // Create logo/brand
        const logo = document.createElement('div');
        logo.className = 'logo';
        logo.innerHTML = '<img src="/static/icon/logo.png" alt="Youcert" onerror="this.style.display=\'none\'"><span>Youcert</span>';

        // Create menu toggle
        const menuToggle = document.createElement('button');
        menuToggle.className = 'mobile-menu-toggle';
        menuToggle.setAttribute('aria-label', 'Menu');
        menuToggle.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>';

        mobileNav.appendChild(logo);
        mobileNav.appendChild(menuToggle);

        // Insert at top of body
        document.body.insertBefore(mobileNav, document.body.firstChild);

        // Create mobile menu
        createMobileMenu(menuToggle);
    }

    // ===================== MOBILE MENU TOGGLE =====================
    function createMobileMenu(toggleButton) {
        // Create mobile menu container
        let mobileMenu = document.querySelector('.mobile-menu');

        if (!mobileMenu) {
            mobileMenu = document.createElement('div');
            mobileMenu.className = 'mobile-menu';

            // Determine page type and create appropriate menu items
            const currentPath = window.location.pathname;
            let menuItems = [];

            if (currentPath.includes('/creator/')) {
                // Creator menu (matching creator_sidebar.html routes)
                menuItems = [
                    { href: '/creator/home/', label: 'Dashboard', icon: 'fa-home' },
                    { href: '/creator/listed_exams/', label: 'Listed Exams', icon: 'fa-list' },
                    { href: '/creator/list_new_exam/', label: 'List New Exam', icon: 'fa-plus-circle' },
                    { href: '/creator/settings/', label: 'Settings', icon: 'fa-cog' },
                    { href: '/creator/bank_accounts/', label: 'Bank Details', icon: 'fa-university' }
                ];
            } else if (currentPath.includes('/naanni/') || currentPath.includes('/admin/')) {
                // Admin menu (comprehensive list from admin_dashboard.html sidebar)
                menuItems = [
                    // Overview
                    { href: '/naanni/dashboard/', label: 'Dashboard', icon: 'fa-home', group: 'Overview' },
                    { href: '/naanni/earnings_analysis/', label: 'My Earnings', icon: 'fa-chart-pie', group: 'Overview' },
                    { href: '/naanni/creator_payment_search/', label: 'Creator Earnings', icon: 'fa-arrow-trend-up', group: 'Overview' },

                    // Users & Support
                    { href: '/naanni/user/', label: 'All Users', icon: 'fa-users', group: 'Users' },
                    { href: '/naanni/user_result/', label: 'Exam Results', icon: 'fa-clipboard-list', group: 'Users' },
                    { href: '/naanni/contact_query/', label: 'Support Queries', icon: 'fa-message', group: 'Users' },

                    // Content
                    { href: '/naanni/exam/', label: 'Exams', icon: 'fa-book-open', group: 'Content' },
                    { href: '/naanni/featured_exams/', label: 'Featured Exams', icon: 'fa-star', group: 'Content' },
                    { href: '/naanni/purchase_exam/', label: 'Purchases', icon: 'fa-shopping-bag', group: 'Content' },
                    { href: '/naanni/creator/', label: 'Creators', icon: 'fa-palette', group: 'Content' },
                    { href: '/naanni/creator_requests/?status=pending', label: 'Join Requests', icon: 'fa-user-plus', group: 'Content' },

                    // Finance
                    { href: '/naanni/bank_verifications/', label: 'Verifications', icon: 'fa-shield-check', group: 'Finance' },
                    { href: '/naanni/bank_details/', label: 'Bank Details', icon: 'fa-credit-card', group: 'Finance' },
                    { href: '/naanni/payout/', label: 'Process Payouts', icon: 'fa-money-bill', group: 'Finance' },

                    // System
                    { href: '/naanni/admin/', label: 'Admins', icon: 'fa-shield', group: 'System' },
                    { href: '/naanni/registration_requests/', label: 'Registration Requests', icon: 'fa-user-check', group: 'System' },
                    { href: '/naanni/documents/', label: 'Documents', icon: 'fa-file-text', group: 'System' },
                    { href: '/naanni/upload_document/', label: 'Upload Document', icon: 'fa-cloud-arrow-up', group: 'System' },
                    { href: '/naanni/logs/', label: 'Audit Logs', icon: 'fa-clock-rotate-left', group: 'System' }
                ];
            } else {
                // User menu (matching user_navbar.html routes)
                menuItems = [
                    { href: '/home/', label: 'Home', icon: 'fa-home' },
                    { href: '/exams/', label: 'Exams', icon: 'fa-book' },
                    { href: '/completed_exams/', label: 'History', icon: 'fa-history' },
                    { href: '/user_profile/', label: 'Profile', icon: 'fa-user' }
                ];
            }

            // Create menu items with group separators for admin
            let lastGroup = null;
            menuItems.forEach(item => {
                // Add group separator for admin menu
                if (item.group && item.group !== lastGroup) {
                    const groupLabel = document.createElement('div');
                    groupLabel.className = 'mobile-menu-group-label';
                    groupLabel.textContent = item.group;
                    mobileMenu.appendChild(groupLabel);
                    lastGroup = item.group;
                }

                const menuItem = document.createElement('a');
                menuItem.href = item.href;
                menuItem.className = 'mobile-menu-item';
                if (currentPath === item.href || (item.href !== '/' && currentPath.startsWith(item.href))) {
                    menuItem.classList.add('active');
                }
                menuItem.innerHTML = `<i class="fas ${item.icon}" style="margin-right: 0.75rem;"></i>${item.label}`;
                mobileMenu.appendChild(menuItem);
            });

            document.body.appendChild(mobileMenu);
        }

        // Toggle functionality
        if (!toggleButton) {
            toggleButton = document.querySelector('.mobile-menu-toggle');
        }

        if (toggleButton && mobileMenu) {
            toggleButton.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                const isActive = mobileMenu.classList.contains('active');

                if (isActive) {
                    mobileMenu.classList.remove('active');
                    toggleButton.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>';
                    document.body.style.overflow = '';
                } else {
                    mobileMenu.classList.add('active');
                    toggleButton.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
                    document.body.style.overflow = 'hidden';
                }
            });

            // Close menu when clicking on a link
            mobileMenu.querySelectorAll('a').forEach(link => {
                link.addEventListener('click', () => {
                    mobileMenu.classList.remove('active');
                    toggleButton.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>';
                    document.body.style.overflow = '';
                });
            });

            // Close menu when clicking outside
            document.addEventListener('click', function (e) {
                if (!mobileMenu.contains(e.target) && !toggleButton.contains(e.target)) {
                    if (mobileMenu.classList.contains('active')) {
                        mobileMenu.classList.remove('active');
                        toggleButton.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>';
                        document.body.style.overflow = '';
                    }
                }
            });
        }
    }

    function initMobileMenu() {
        if (!isMobile()) return;

        // Check if there's already a nav element
        const existingNav = document.querySelector('.header-nav, .navbar, .top-navbar');

        if (existingNav) {
            // Add mobile toggle to existing nav
            let mobileToggle = existingNav.querySelector('.mobile-menu-toggle');

            if (!mobileToggle) {
                mobileToggle = document.createElement('button');
                mobileToggle.className = 'mobile-menu-toggle';
                mobileToggle.setAttribute('aria-label', 'Toggle mobile menu');
                mobileToggle.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>';

                // Find the best place to insert it
                const navContainer = existingNav.querySelector('.container, .container-fluid, div');
                if (navContainer) {
                    navContainer.appendChild(mobileToggle);
                } else {
                    existingNav.appendChild(mobileToggle);
                }
            }

            createMobileMenu(mobileToggle);
        } else {
            // No nav exists - create one
            createMobileNavBar();
        }
    }

    // ===================== SIDEBAR MOBILE TOGGLE =====================
    function initSidebarMobile() {
        // Only run on mobile/tablet
        if (!isTablet() && !isMobile()) return;

        const sidebar = document.querySelector('.sidebar, .creator-sidebar, .admin-sidebar');
        if (!sidebar) return;

        // Ensure sidebar starts hidden on mobile
        sidebar.classList.remove('active');

        // Check if there's a header to attach the toggle to
        let header = document.querySelector('.header-nav, .navbar, .page-header');

        // If no header exists AND we're actually on mobile/tablet, create a mobile nav bar
        if (!header && (isMobile() || isTablet())) {
            header = document.createElement('nav');
            header.className = 'mobile-nav-bar';

            // Add logo
            const logo = document.createElement('div');
            logo.className = 'logo';
            logo.innerHTML = '<img src="/static/icon/logo.png" alt="Youcert" style="height: 32px;" onerror="this.style.display=\'none\'"><span style="margin-left: 0.5rem;">Youcert</span>';
            header.appendChild(logo);

            // Insert at the beginning of body
            document.body.insertBefore(header, document.body.firstChild);
        }

        // If no header found or created (desktop mode), return early
        if (!header) return;

        // Create sidebar toggle button
        let sidebarToggle = document.querySelector('.sidebar-toggle');
        if (!sidebarToggle) {
            sidebarToggle = document.createElement('button');
            sidebarToggle.className = 'sidebar-toggle';
            sidebarToggle.setAttribute('aria-label', 'Toggle sidebar');

            // Use inline SVG hamburger icon (works universally)
            sidebarToggle.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            `;

            // Insert toggle button at the end of header
            header.appendChild(sidebarToggle);
        }

        // Create overlay
        let overlay = document.querySelector('.sidebar-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'sidebar-overlay';
            document.body.appendChild(overlay);
        }

        // Toggle functionality (check if already has listener)
        if (!sidebarToggle.hasAttribute('data-listener-attached')) {
            sidebarToggle.setAttribute('data-listener-attached', 'true');
            sidebarToggle.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                sidebar.classList.toggle('active');
                overlay.classList.toggle('active');

                if (sidebar.classList.contains('active')) {
                    document.body.style.overflow = 'hidden';
                } else {
                    document.body.style.overflow = '';
                }
            });
        }

        // Close on overlay click
        if (!overlay.hasAttribute('data-listener-attached')) {
            overlay.setAttribute('data-listener-attached', 'true');
            overlay.addEventListener('click', function () {
                sidebar.classList.remove('active');
                overlay.classList.remove('active');
                document.body.style.overflow = '';
            });
        }

        // Close on sidebar link click
        sidebar.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                if (isMobile() || isTablet()) {
                    sidebar.classList.remove('active');
                    overlay.classList.remove('active');
                    document.body.style.overflow = '';
                }
            });
        });
    }

    // ===================== TOUCH SWIPE GESTURES =====================
    function initSwipeGestures() {
        if (!isTouchDevice()) return;

        let touchStartX = 0;
        let touchEndX = 0;
        let touchStartY = 0;
        let touchEndY = 0;

        const carousels = document.querySelectorAll('.carousel-inner, .slider-wrapper, .exam-carousel');

        carousels.forEach(carousel => {
            carousel.addEventListener('touchstart', function (e) {
                touchStartX = e.changedTouches[0].screenX;
                touchStartY = e.changedTouches[0].screenY;
            }, { passive: true });

            carousel.addEventListener('touchend', function (e) {
                touchEndX = e.changedTouches[0].screenX;
                touchEndY = e.changedTouches[0].screenY;

                const deltaX = touchEndX - touchStartX;
                const deltaY = touchEndY - touchStartY;

                // Only trigger swipe if horizontal movement is greater than vertical
                if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 50) {
                    if (deltaX > 0) {
                        // Swipe right - previous
                        const prevBtn = carousel.parentElement.querySelector('.carousel-prev, .prev-btn');
                        if (prevBtn) prevBtn.click();
                    } else {
                        // Swipe left - next
                        const nextBtn = carousel.parentElement.querySelector('.carousel-next, .next-btn');
                        if (nextBtn) nextBtn.click();
                    }
                }
            }, { passive: true });
        });
    }

    // ===================== MODAL MOBILE OPTIMIZATION =====================
    function initModalMobile() {
        const modals = document.querySelectorAll('.modal');

        modals.forEach(modal => {
            // When modal opens on mobile, prevent body scroll
            const observer = new MutationObserver(function (mutations) {
                mutations.forEach(function (mutation) {
                    if (mutation.attributeName === 'class') {
                        const isOpen = modal.classList.contains('show') ||
                            modal.classList.contains('active') ||
                            modal.style.display === 'block' ||
                            modal.style.display === 'flex';

                        if (isMobile()) {
                            if (isOpen) {
                                document.body.style.overflow = 'hidden';
                                document.body.style.position = 'fixed';
                                document.body.style.width = '100%';
                            } else {
                                document.body.style.overflow = '';
                                document.body.style.position = '';
                                document.body.style.width = '';
                            }
                        }
                    }
                });
            });

            observer.observe(modal, { attributes: true });
        });
    }

    // ===================== TABLE MOBILE CARDS =====================
    function initTableMobileCards() {
        if (!isMobile()) return;

        const tables = document.querySelectorAll('table:not(.table-responsive table)');

        tables.forEach(table => {
            // Add data-label attributes for mobile card view
            const headers = table.querySelectorAll('thead th');
            const rows = table.querySelectorAll('tbody tr');

            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                cells.forEach((cell, index) => {
                    if (headers[index]) {
                        cell.setAttribute('data-label', headers[index].textContent.trim());
                    }
                });
            });

            // Add mobile card class
            table.classList.add('table-mobile-cards');
        });
    }

    // ===================== FORM INPUT ZOOM PREVENTION (iOS) =====================
    function preventIOSInputZoom() {
        if (!isTouchDevice()) return;

        const inputs = document.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            const currentFontSize = window.getComputedStyle(input).fontSize;
            const fontSize = parseFloat(currentFontSize);

            // iOS zooms if font-size is less than 16px
            if (fontSize < 16) {
                input.style.fontSize = '16px';
            }
        });
    }

    // ===================== STICKY HEADER SCROLL BEHAVIOR =====================
    function initStickyHeaderBehavior() {
        const header = document.querySelector('.header-nav, .navbar, .top-navbar');
        if (!header) return;

        let lastScrollTop = 0;
        let scrolling = false;

        window.addEventListener('scroll', function () {
            if (!scrolling) {
                window.requestAnimationFrame(function () {
                    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

                    if (isMobile()) {
                        if (scrollTop > lastScrollTop && scrollTop > 100) {
                            // Scrolling down - hide header
                            header.style.transform = 'translateY(-100%)';
                        } else {
                            // Scrolling up - show header
                            header.style.transform = 'translateY(0)';
                        }
                    }

                    // Add shadow when scrolled
                    if (scrollTop > 10) {
                        header.style.boxShadow = '0 2px 12px rgba(0,0,0,0.08)';
                    } else {
                        header.style.boxShadow = '';
                    }

                    lastScrollTop = scrollTop;
                    scrolling = false;
                });

                scrolling = true;
            }
        }, { passive: true });

        // Smooth transition
        header.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease';
    }

    // ===================== BOTTOM NAVIGATION INITIALIZATION =====================
    function initBottomNavigation() {
        // Check if page should have bottom nav
        const bottomNav = document.querySelector('.bottom-nav');
        if (bottomNav && isMobile()) {
            document.body.classList.add('has-bottom-nav');

            // Set active state based on current page
            const currentPath = window.location.pathname;
            const navItems = bottomNav.querySelectorAll('.bottom-nav-item');

            navItems.forEach(item => {
                const href = item.getAttribute('href');
                if (href && currentPath.includes(href)) {
                    item.classList.add('active');
                }
            });
        }
    }

    // ===================== RESPONSIVE GRID AUTO-ADJUSTMENT =====================
    function initResponsiveGrids() {
        if (!isMobile()) return;

        const grids = document.querySelectorAll('[class*="grid-cols-"]');
        grids.forEach(grid => {
            // Force single column on mobile
            grid.style.gridTemplateColumns = '1fr';
        });
    }

    // ===================== IMAGE LAZY LOADING =====================
    function initLazyLoading() {
        if ('IntersectionObserver' in window) {
            const lazyImages = document.querySelectorAll('img[data-src]');

            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                        imageObserver.unobserve(img);
                    }
                });
            });

            lazyImages.forEach(img => imageObserver.observe(img));
        }
    }

    // ===================== PULL TO REFRESH (OPTIONAL) =====================
    function initPullToRefresh() {
        if (!isMobile() || !isTouchDevice()) return;

        let touchStartY = 0;
        let pullDistance = 0;
        const threshold = 80;

        document.addEventListener('touchstart', function (e) {
            if (window.scrollY === 0) {
                touchStartY = e.touches[0].clientY;
            }
        }, { passive: true });

        document.addEventListener('touchmove', function (e) {
            if (touchStartY > 0) {
                pullDistance = e.touches[0].clientY - touchStartY;

                if (pullDistance > 0 && pullDistance < threshold * 2) {
                    // Visual feedback here (optional)
                }
            }
        }, { passive: true });

        document.addEventListener('touchend', function () {
            if (pullDistance > threshold) {
                // Reload page
                window.location.reload();
            }
            touchStartY = 0;
            pullDistance = 0;
        }, { passive: true });
    }

    // ===================== VIEWPORT HEIGHT FIX (Mobile browsers) =====================
    function fixMobileViewportHeight() {
        // Fix for mobile browsers where 100vh includes the address bar
        const setVH = () => {
            const vh = window.innerHeight * 0.01;
            document.documentElement.style.setProperty('--vh', `${vh}px`);
        };

        setVH();
        window.addEventListener('resize', setVH);
        window.addEventListener('orientationchange', setVH);
    }

    // ===================== PREVENT DOUBLE-TAP ZOOM =====================
    function preventDoubleTapZoom() {
        if (!isTouchDevice()) return;

        let lastTouchEnd = 0;

        document.addEventListener('touchend', function (e) {
            const now = Date.now();
            if (now - lastTouchEnd <= 300) {
                e.preventDefault();
            }
            lastTouchEnd = now;
        }, { passive: false });
    }

    // ===================== CSRF TOKEN PRESERVATION =====================
    function ensureCSRFTokens() {
        // Get CSRF token from meta tag
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : null;

        if (csrfToken) {
            // Add CSRF token to all AJAX requests
            const originalFetch = window.fetch;
            window.fetch = function (url, options = {}) {
                if (!options.headers) {
                    options.headers = {};
                }

                if (typeof options.headers.append === 'function') {
                    options.headers.append('X-CSRFToken', csrfToken);
                } else {
                    options.headers['X-CSRFToken'] = csrfToken;
                }

                return originalFetch(url, options);
            };

            // Add CSRF token to all forms
            const forms = document.querySelectorAll('form');
            forms.forEach(form => {
                let csrfInput = form.querySelector('input[name="csrf_token"]');
                if (!csrfInput) {
                    csrfInput = document.createElement('input');
                    csrfInput.type = 'hidden';
                    csrfInput.name = 'csrf_token';
                    csrfInput.value = csrfToken;
                    form.appendChild(csrfInput);
                }
            });
        }
    }

    // ===================== ORIENTATION CHANGE HANDLER =====================
    function handleOrientationChange() {
        window.addEventListener('orientationchange', function () {
            // Small delay to ensure new dimensions are available
            setTimeout(() => {
                // Reinitialize certain components
                initResponsiveGrids();
                initTableMobileCards();
            }, 100);
        });
    }

    // ===================== RESPONSIVE VIEWPORT CHANGE HANDLER =====================
    function handleResponsiveChanges() {
        let wasMobile = isMobile();
        let wasTablet = isTablet();

        window.addEventListener('resize', function () {
            const nowMobile = isMobile();
            const nowTablet = isTablet();

            // Detect mobile <-> desktop transition
            if (wasMobile !== nowMobile || wasTablet !== nowTablet) {
                // Clean up and reinitialize
                cleanupMobileComponents();

                setTimeout(() => {
                    if (nowMobile) {
                        // Switched to mobile
                        initMobileMenu();
                        initResponsiveGrids();
                        initTableMobileCards();
                        document.body.classList.add('is-mobile');
                        document.body.classList.remove('is-desktop');
                    } else {
                        // Switched to desktop
                        document.body.classList.add('is-desktop');
                        document.body.classList.remove('is-mobile');

                        // Remove mobile menu if it exists
                        const mobileMenu = document.querySelector('.mobile-menu');
                        const mobileNavBar = document.querySelector('.mobile-nav-bar');
                        if (mobileMenu) mobileMenu.remove();
                        if (mobileNavBar) mobileNavBar.remove();

                        // Reset body overflow
                        document.body.style.overflow = '';
                    }

                    wasMobile = nowMobile;
                    wasTablet = nowTablet;
                }, 100);
            }
        });
    }

    function cleanupMobileComponents() {
        // Remove mobile menu toggle buttons
        const toggles = document.querySelectorAll('.mobile-menu-toggle');
        toggles.forEach(toggle => {
            if (!toggle.closest('.mobile-nav-bar')) {
                toggle.remove();
            }
        });

        // Reset body overflow
        document.body.style.overflow = '';

        // Close any open menus
        const mobileMenu = document.querySelector('.mobile-menu');
        if (mobileMenu) {
            mobileMenu.classList.remove('active');
        }

        // Close sidebars
        const sidebar = document.querySelector('.sidebar.active, .creator-sidebar.active, .admin-sidebar.active');
        const overlay = document.querySelector('.sidebar-overlay.active');
        if (sidebar) sidebar.classList.remove('active');
        if (overlay) overlay.classList.remove('active');
    }

    // ===================== PERFORMANCE OPTIMIZATION =====================
    function optimizePerformance() {
        // Debounce resize events
        let resizeTimer;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                // Reinitialize components that depend on viewport size
                if (isMobile()) {
                    initResponsiveGrids();
                    initTableMobileCards();
                }
            }, 250);
        });

        // Reduce motion for users who prefer it
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            document.documentElement.style.setProperty('--transition-smooth', 'none');
        }
    }

    // ===================== INITIALIZE ALL MOBILE FEATURES =====================
    function init() {
        // Set initial body class
        if (isMobile()) {
            document.body.classList.add('is-mobile');
        } else {
            document.body.classList.add('is-desktop');
        }

        // Mark if page has sidebar
        const sidebar = document.querySelector('.sidebar, .creator-sidebar, .admin-sidebar');
        if (sidebar) {
            document.body.classList.add('has-sidebar');
        }

        // Core features
        ensureCSRFTokens();
        fixMobileViewportHeight();
        preventIOSInputZoom();

        // Navigation
        initMobileMenu();
        initSidebarMobile();
        initBottomNavigation();
        initStickyHeaderBehavior();

        // Content adaptations
        initResponsiveGrids();
        initTableMobileCards();
        initModalMobile();

        // Interactions
        initSwipeGestures();
        preventDoubleTapZoom();

        // Responsive handling
        handleResponsiveChanges();

        // Performance
        initLazyLoading();
        optimizePerformance();
        handleOrientationChange();

        // Optional features (can be disabled if not needed)
        // initPullToRefresh();
    }

    // ===================== AUTO-INITIALIZE =====================
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export functions for manual initialization if needed
    window.YoucertMobile = {
        init,
        isMobile,
        isTablet,
        isTouchDevice,
        initMobileMenu,
        initSidebarMobile,
        initSwipeGestures,
        initModalMobile,
        initTableMobileCards,
        ensureCSRFTokens
    };

})();
