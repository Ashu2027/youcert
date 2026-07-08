-- =====================================================================
-- COMPLETE MASTER DATABASE SETUP (V15.1 - CLOUD COMPATIBLE)
-- Combined Schemas: user_base, creator_base, exam, query_base, admin_base
-- Compatible with: Google Cloud SQL MySQL, Windows MySQL, Linux MySQL
-- Includes: Optimized Limits, Logic, Atomic Admin Procedures, Analysis Tools,
--           Database OTP/Lockout (No Filesystem), Multi-Instance Cloud Run Ready
--           Creator Bank Account Toggling Logic
-- RESTORED: Safety Constraints for Admin Designations
-- FIX: Added proper table drop order + Cloud SQL compatibility
-- =====================================================================

-- =====================================================================
-- CRITICAL FIX: Drop tables with foreign keys BEFORE dropping databases
-- =====================================================================
DROP TABLE IF EXISTS admin_base.promotional_exams_cache;
DROP TABLE IF EXISTS admin_base.admin_featured_exams;
DROP TABLE IF EXISTS admin_base.password_reset_tokens;
DROP TABLE IF EXISTS admin_base.otp_tokens;

-- Safety: drop existing databases
DROP DATABASE IF EXISTS user_base;
DROP DATABASE IF EXISTS creator_base;
DROP DATABASE IF EXISTS exam;
DROP DATABASE IF EXISTS query_base;
DROP DATABASE IF EXISTS admin_base;

-- Create databases
CREATE DATABASE user_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE creator_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE exam CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE query_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE admin_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =====================================================================
-- COMPLETE MASTER DATABASE SETUP (V15.0 - DATABASE-ONLY)
-- Combined Schemas: user_base, creator_base, exam, query_base, admin_base
-- Includes: Optimized Limits, Logic, Atomic Admin Procedures, Analysis Tools,
--           Database OTP/Lockout (No Filesystem), Multi-Instance Cloud Run Ready
--           Creator Bank Account Toggling Logic
-- RESTORED: Safety Constraints for Admin Designations
-- =====================================================================


-- =====================================================================
-- 1. USER_BASE SCHEMA (users and results)
-- =====================================================================

USE user_base;

-- User Table
CREATE TABLE user (
    user_id VARCHAR(120) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    name_in_certificate VARCHAR(600) NULL DEFAULT NULL COMMENT 'Name to be printed on certificates; defaults to user.name if NULL',
    email VARCHAR(250) NOT NULL UNIQUE,
    password_hash VARCHAR(1024) DEFAULT '',
    phone VARCHAR(60),
    date_of_birth DATE,
    gender ENUM('male','female','other','prefer_not_to_say'),
    address MEDIUMTEXT,
    oauth_token VARCHAR(1536),
    refresh_token VARCHAR(1536),
    client_id VARCHAR(765),
    client_secret VARCHAR(765),
    token_uri VARCHAR(765),
    token_expiry TIMESTAMP NULL,
    profile_picture VARCHAR(1500),
    email_verified BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_name (name),
    INDEX idx_created_at (created_at),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User Result Table
CREATE TABLE user_result (
    id INT AUTO_INCREMENT PRIMARY KEY,
    unique_order_number VARCHAR(120) NOT NULL UNIQUE,
    user_id VARCHAR(120) NOT NULL,
    channel_id VARCHAR(120) NOT NULL,
    unique_exam_number VARCHAR(120) NOT NULL,
    payment_date DATE NOT NULL,
    payment_time TIME NOT NULL,
    payment_id VARCHAR(300) NOT NULL UNIQUE,
    amount_paid DECIMAL(10,2) NOT NULL,
    marks_obtained INT NOT NULL,
    total_marks INT NOT NULL,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    attempt_number INT DEFAULT 1,
    passing_marks INT DEFAULT 60,
    time_taken INT,
    certificate_url VARCHAR(1500),
    INDEX idx_user_id (user_id),
    INDEX idx_exam (unique_exam_number),
    INDEX idx_purchase (unique_order_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 2. CREATOR_BASE SCHEMA (creators, playlists, videos, bank info)
-- =====================================================================

USE creator_base;

-- Creators Table
CREATE TABLE creators (
    channel_id VARCHAR(120) PRIMARY KEY,
    email VARCHAR(250) NOT NULL UNIQUE,
    password_hash VARCHAR(1024) NOT NULL,
    creator_name VARCHAR(150) NOT NULL,
    channel_name VARCHAR(765) NOT NULL,
    subscriber_count BIGINT DEFAULT 0,
    youtube_channel_link VARCHAR(765),
    profile_photo_jpg VARCHAR(1500),
    signature_jpg_file VARCHAR(1500),
    oauth_token VARCHAR(1536),
    refresh_token VARCHAR(1536),
    client_id VARCHAR(765),
    client_secret VARCHAR(765),
    token_uri VARCHAR(765),
    token_expiry TIMESTAMP NULL,
    oauth_connected BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_creator_name (creator_name),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE creator_base.summary_cache (
    chunk_hash VARCHAR(192) PRIMARY KEY,
    summary_text LONGTEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at)
) ENGINE=InnoDB;

-- Playlists Table
CREATE TABLE playlists (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id VARCHAR(120) NOT NULL,
    playlist_id VARCHAR(120) NOT NULL UNIQUE,
    playlist_title VARCHAR(1500) NOT NULL,
    playlist_description LONGTEXT,
    thumbnail_image VARCHAR(1500) DEFAULT NULL,
    transcript_path VARCHAR(1500) DEFAULT NULL,
    video_count INT DEFAULT 0,
    summary_path VARCHAR(1500),
    duration_seconds INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_channel_id (channel_id),
    INDEX idx_playlist_id (playlist_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Videos Table
CREATE TABLE videos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id VARCHAR(120) NOT NULL,
    video_id VARCHAR(60) NOT NULL UNIQUE,
    title VARCHAR(1500) NOT NULL,
    video_description MEDIUMTEXT,
    thumbnail_image VARCHAR(1500),
    transcript_path VARCHAR(1500),
    summary_path VARCHAR(1500),
    playlist_id VARCHAR(120) NULL,
    playlist_index INT DEFAULT NULL,
    duration_seconds INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_channel_id (channel_id),
    INDEX idx_video_id (video_id),
    INDEX idx_playlist_id (playlist_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Creator Bank Information
CREATE TABLE creator_bank_info (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id VARCHAR(120) NOT NULL,

    -- Basic Information
    account_holder_name VARCHAR(600) NOT NULL COMMENT 'Full name as per bank account',
    bank_name VARCHAR(600) NOT NULL COMMENT 'Name of the bank',
    branch_name VARCHAR(600) COMMENT 'Bank branch name',

    -- Account Details
    account_number VARCHAR(3000) NOT NULL COMMENT 'Bank account number (encrypted in app)',
    account_type ENUM('savings', 'current', 'business') DEFAULT 'savings',

    -- Indian Banking
    ifsc_code VARCHAR(60) COMMENT 'IFSC code for NEFT/RTGS/UPI transfers',

    -- International Banking
    swift_code VARCHAR(60) COMMENT 'SWIFT/BIC code for international transfers',
    iban VARCHAR(150) COMMENT 'International Bank Account Number',
    routing_number VARCHAR(60) COMMENT 'Bank routing number (US/Canada)',
    sort_code VARCHAR(30) COMMENT 'Sort code (UK)',
    bsb_number VARCHAR(30) COMMENT 'Bank State Branch number (Australia)',

    -- Address Information
    bank_address MEDIUMTEXT COMMENT 'Bank branch address',
    account_holder_address MEDIUMTEXT NOT NULL COMMENT 'Account holder residential address',
    country_code VARCHAR(9) NOT NULL DEFAULT 'IND' COMMENT 'ISO country code',
    currency_code VARCHAR(9) NOT NULL DEFAULT 'INR' COMMENT 'Account currency',

    -- Government ID
    id_type ENUM('aadhaar', 'pan', 'passport', 'driving_license', 'voter_id', 'other') NOT NULL COMMENT 'Type of government ID',
    id_number VARCHAR(3000) NOT NULL COMMENT 'Government ID number (encrypted in app)',
    id_image_path VARCHAR(1500) NOT NULL COMMENT 'Path to uploaded government ID image',

    -- Bank Verification Document
    bank_document_path VARCHAR(1500) NOT NULL COMMENT 'Path to bank statement or passbook image',

    -- Verification & Security
    verification_status TINYINT(1) DEFAULT 0 COMMENT '0=Pending, 1=Verified, 2=Rejected, 3=Under Review',
    is_active TINYINT(1) DEFAULT 1 COMMENT 'Admin control to enable/disable payments',
    is_frozen TINYINT(1) DEFAULT 0 COMMENT 'Emergency freeze flag for security',

    -- Verification Details
    verified_by VARCHAR(150) COMMENT 'Admin who verified the account',
    verified_at TIMESTAMP NULL COMMENT 'When account was verified',
    rejection_reason MEDIUMTEXT COMMENT 'Reason if verification was rejected',

    -- Audit Trail
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(150) DEFAULT 'CREATOR' COMMENT 'Who created this record',
    updated_by VARCHAR(150) COMMENT 'Who last updated this record',

    -- Constraints and Indexes
    INDEX idx_channel_id (channel_id),
    INDEX idx_verification_status (verification_status),
    INDEX idx_is_active (is_active),
    INDEX idx_is_frozen (is_frozen),
    INDEX idx_country_code (country_code),
    INDEX idx_id_type (id_type),
    INDEX idx_created_at (created_at),

    -- Ensure at least one banking method is provided
    CONSTRAINT chk_banking_method CHECK (
        (ifsc_code IS NOT NULL) OR 
        (swift_code IS NOT NULL) OR 
        (iban IS NOT NULL) OR 
        (routing_number IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Creator banking information with simplified ID storage';

-- Video Processing Status Table
CREATE TABLE video_processing_status (
    content_id VARCHAR(100) NOT NULL COMMENT 'Video ID',
    channel_id VARCHAR(100) NOT NULL COMMENT 'Channel ID',

    -- Status and Metadata
    status VARCHAR(50) NOT NULL DEFAULT 'processing' COMMENT 'processing/completed/chunks_generated/failed',
    chunk_count INT DEFAULT NULL COMMENT 'Updated by chunk_generation worker',

    -- Progress Tracking for Long Videos
    total_chunks INT DEFAULT NULL COMMENT 'Total number of chunks to process',
    processed_chunks INT DEFAULT 0 COMMENT 'Number of chunks processed so far',
    progress_percentage DECIMAL(5,2) DEFAULT 0.00 COMMENT 'Processing progress (0-100)',
    current_stage VARCHAR(100) DEFAULT NULL COMMENT 'Current processing stage description',

    -- Checkpoint Recovery
    checkpoint_data JSON DEFAULT NULL COMMENT 'Stores processed chunk results for recovery',
    last_successful_chunk INT DEFAULT NULL COMMENT 'Last successfully processed chunk index',

    -- File paths for worker access
    transcript_path VARCHAR(1000) DEFAULT NULL,
    summary_path VARCHAR(1000) DEFAULT NULL,

    -- Error Handling and Audit
    error_message TEXT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    -- CRITICAL: Primary Key must be the IDs for "ON DUPLICATE KEY UPDATE" to work
    PRIMARY KEY (content_id, channel_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Playlist Processing Status Table
CREATE TABLE playlist_processing_status (
    content_id VARCHAR(100) NOT NULL COMMENT 'Playlist ID',
    channel_id VARCHAR(100) NOT NULL COMMENT 'Channel ID',

    status VARCHAR(50) NOT NULL DEFAULT 'processing',
    chunk_count INT DEFAULT NULL,

    -- Progress Tracking for Long Playlists
    total_chunks INT DEFAULT NULL COMMENT 'Total number of chunks to process',
    processed_chunks INT DEFAULT 0 COMMENT 'Number of chunks processed so far',
    progress_percentage DECIMAL(5,2) DEFAULT 0.00 COMMENT 'Processing progress (0-100)',
    current_stage VARCHAR(100) DEFAULT NULL COMMENT 'Current processing stage description',

    -- Checkpoint Recovery
    checkpoint_data JSON DEFAULT NULL COMMENT 'Stores processed chunk results for recovery',
    last_successful_chunk INT DEFAULT NULL COMMENT 'Last successfully processed chunk index',

    summary_path VARCHAR(1000) DEFAULT NULL,

    error_message TEXT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    -- CRITICAL: Primary Key must be the IDs for "ON DUPLICATE KEY UPDATE" to work
    PRIMARY KEY (content_id, channel_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 3. EXAM SCHEMA
-- =====================================================================

USE exam;

-- Listed Exams Table
CREATE TABLE listed_exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    unique_exam_number VARCHAR(120) NOT NULL UNIQUE,
    channel_id VARCHAR(120) NOT NULL,
    video_id VARCHAR(60) NULL,
    playlist_id VARCHAR(120) NULL,
    thumbnail_image VARCHAR(1500),
    transcript_path VARCHAR(1500),
    summary_path VARCHAR(1500),
    channel_name VARCHAR(765) NOT NULL,
    number_of_subscribers BIGINT DEFAULT 0,
    exam_title VARCHAR(1500),
    exam_description MEDIUMTEXT,
    exam_price DECIMAL(10,2) DEFAULT 0.00,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_unique_exam_number (unique_exam_number),
    INDEX idx_channel_id (channel_id),
    INDEX idx_video_id (video_id),
    INDEX idx_playlist_id (playlist_id),
    INDEX idx_channel_name (channel_name),
    INDEX idx_is_active (is_active),
    CONSTRAINT chk_content_type CHECK (
        (video_id IS NOT NULL AND playlist_id IS NULL) OR 
        (video_id IS NULL AND playlist_id IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Purchased Exams Table
CREATE TABLE purchased_exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    unique_order_number VARCHAR(120) NOT NULL UNIQUE,
    user_id VARCHAR(120) NOT NULL,
    channel_id VARCHAR(120) NOT NULL,
    unique_exam_number VARCHAR(120) NOT NULL,
    payment_date DATE NOT NULL,
    payment_time TIME NOT NULL,
    payment_id VARCHAR(300) NOT NULL UNIQUE,
    amount_paid DECIMAL(10,2) NOT NULL,
    payment_status ENUM('pending', 'completed', 'failed', 'refunded') DEFAULT 'completed',
    payment_method VARCHAR(120),
    razorpay_order_id VARCHAR(300),
    razorpay_payment_id VARCHAR(300),
    razorpay_signature VARCHAR(765),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_unique_order_number (unique_order_number),
    INDEX idx_user_id (user_id),
    INDEX idx_channel_id (channel_id),
    INDEX idx_unique_exam_number (unique_exam_number),
    INDEX idx_payment_id (payment_id),
    INDEX idx_payment_date (payment_date),
    INDEX idx_payment_status (payment_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Exam Questions Table (JSON store)
CREATE TABLE exam_questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    unique_exam_number VARCHAR(120) NOT NULL,
    questions_json LONGTEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_unique_exam_questions (unique_exam_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================

-- Exam Attempts Table (CLIENT-SIDE EXAM SYSTEM)
CREATE TABLE exam_attempts (
    attempt_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(120) NOT NULL,
    exam_id VARCHAR(120) NOT NULL,
    score INT,
    correct_count INT,
    total_questions INT,
    time_taken INT,
    passed BOOLEAN DEFAULT FALSE,
    certificate_path VARCHAR(255),
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_exam (user_id, exam_id),
    INDEX idx_user_id (user_id),
    INDEX idx_exam_id (exam_id),
    INDEX idx_passed (passed),
    INDEX idx_completed_at (completed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Stores exam attempt results from client-side grading system';

-- User Exam Answers Table (CLIENT-SIDE EXAM SYSTEM)
CREATE TABLE user_exam_answers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(120) NOT NULL,
    exam_id VARCHAR(120) NOT NULL,
    answers_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_exam (user_id, exam_id),
    INDEX idx_user_id (user_id),
    INDEX idx_exam_id (exam_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores user answers for exam review (client-side exam system)';


-- =====================================================================
-- 4. QUERY DATABASE SCHEMA
-- =====================================================================

USE query_base;

-- Contact Us Queries Table
CREATE TABLE contact_us_queries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    query_id VARCHAR(120) NOT NULL UNIQUE COMMENT 'Unique identifier',
    name VARCHAR(150) NOT NULL COMMENT 'Visitor name',
    email VARCHAR(250) NOT NULL COMMENT 'Visitor email',
    phone VARCHAR(60) COMMENT 'Visitor phone',
    subject VARCHAR(1500) NOT NULL COMMENT 'Query subject',
    message LONGTEXT NOT NULL COMMENT 'Query message',
    visitor_ip VARCHAR(135) COMMENT 'Visitor IP address',
    resolved TINYINT(1) DEFAULT 0 COMMENT '0=unresolved, 1=resolved',
    resolved_at TIMESTAMP NULL COMMENT 'When admin marked as resolved',
    resolved_by VARCHAR(765) COMMENT 'Admin user_id who marked as resolved',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When query was submitted',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_query_id (query_id),
    INDEX idx_email (email),
    INDEX idx_visitor_ip (visitor_ip),
    INDEX idx_submitted_at (submitted_at),
    INDEX idx_resolved (resolved)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Daily Contact Quota Table
CREATE TABLE contact_daily_quota (
    id INT AUTO_INCREMENT PRIMARY KEY,
    visitor_ip VARCHAR(135) NOT NULL,
    quota_date DATE NOT NULL,
    queries_today INT DEFAULT 0,
    max_queries_per_day INT DEFAULT 10,
    last_query_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_quota (visitor_ip, quota_date),
    INDEX idx_visitor_ip (visitor_ip),
    INDEX idx_quota_date (quota_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Creator Join Requests
CREATE TABLE creator_join_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(120) NOT NULL UNIQUE,
    name VARCHAR(150) NOT NULL,
    channel_name VARCHAR(765) NOT NULL,
    channel_link VARCHAR(765) NOT NULL,
    content_type VARCHAR(300) NOT NULL,
    subscriber_count BIGINT DEFAULT 0,
    email VARCHAR(250) NOT NULL,
    contact_number VARCHAR(60) NOT NULL,
    status ENUM('pending', 'reviewed', 'contacted', 'rejected', 'approved') DEFAULT 'pending',
    visitor_ip VARCHAR(135),
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_email (email),
    INDEX idx_status (status),
    INDEX idx_submitted_at (submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 5. ADMIN DATABASE SCHEMA (Upgraded with Constraints)
-- =====================================================================

USE admin_base;

-- Admins Table
CREATE TABLE admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id VARCHAR(50) NOT NULL UNIQUE COMMENT 'Unique admin identifier',
    email VARCHAR(255) NOT NULL UNIQUE,
    contact_number VARCHAR(20),
    password_hash VARCHAR(255) NOT NULL,
    designation TINYINT NOT NULL COMMENT '0=Supreme, 1=Chief, 2=Major, 3=Hero',
    name VARCHAR(100) NOT NULL,
    hoster_id VARCHAR(50) COMMENT 'Admin ID who created this account',
    login_attempts INT DEFAULT 0,
    locked_until TIMESTAMP NULL,
    last_login TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_approved BOOLEAN DEFAULT FALSE,
    date_joined TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_admin_id (admin_id),
    INDEX idx_email (email),
    INDEX idx_designation (designation),
    INDEX idx_hoster_id (hoster_id),
    INDEX idx_is_active (is_active),
    INDEX idx_is_approved (is_approved),
    CONSTRAINT chk_designation CHECK (designation IN (0, 1, 2, 3))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Registration Requests Table
CREATE TABLE registration_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    contact_number VARCHAR(20) NOT NULL,
    reason TEXT NOT NULL,
    requested_designation TINYINT NOT NULL DEFAULT 3,
    requested_by VARCHAR(50),
    status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    approved_by VARCHAR(50),
    approved_at TIMESTAMP NULL,
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_email (email),
    INDEX idx_status (status),
    CONSTRAINT chk_requested_designation CHECK (requested_designation IN (1, 2, 3))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Admin Logs Table
CREATE TABLE admin_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    admin_id VARCHAR(50) NOT NULL,
    action_code VARCHAR(10) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    details TEXT,
    ip_address VARCHAR(45),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_admin_id (admin_id),
    INDEX idx_action_code (action_code),
    INDEX idx_target_type (target_type),
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bank Verifications Table
CREATE TABLE bank_verifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    bank_info_id INT NOT NULL,
    verified_by VARCHAR(50) NOT NULL,
    verification_status TINYINT NOT NULL COMMENT '0=Pending, 1=Verified, 2=Rejected, 3=Under Review',
    verification_notes TEXT,
    documents_verified BOOLEAN DEFAULT FALSE,
    id_verified BOOLEAN DEFAULT FALSE,
    bank_details_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_channel_id (channel_id),
    INDEX idx_bank_info_id (bank_info_id),
    INDEX idx_verified_by (verified_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Monthly Payouts Table
CREATE TABLE monthly_payouts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    payout_month VARCHAR(7) NOT NULL UNIQUE COMMENT 'YYYY-MM format',
    processed_by VARCHAR(50) NOT NULL,
    total_creators INT DEFAULT 0,
    total_amount DECIMAL(15,2) DEFAULT 0.00,
    platform_commission DECIMAL(15,2) DEFAULT 0.00,
    transfer_charges DECIMAL(15,2) DEFAULT 0.00,
    status ENUM('processing', 'completed', 'failed') DEFAULT 'processing',
    processing_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    INDEX idx_payout_month (payout_month),
    INDEX idx_processed_by (processed_by),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Payout Details Table
CREATE TABLE payout_details (
    id INT AUTO_INCREMENT PRIMARY KEY,
    payout_id INT NOT NULL,
    channel_id VARCHAR(50) NOT NULL,
    gross_earnings DECIMAL(12,2) NOT NULL,
    platform_commission DECIMAL(12,2) NOT NULL,
    transfer_charge DECIMAL(12,2) NOT NULL,
    net_payout DECIMAL(12,2) NOT NULL,
    payment_method VARCHAR(50),
    transaction_id VARCHAR(100),
    payment_status ENUM('pending', 'completed', 'failed', 'skipped') DEFAULT 'pending',
    failure_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP NULL,
    INDEX idx_payout_id (payout_id),
    INDEX idx_channel_id (channel_id),
    INDEX idx_payment_status (payment_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Admin Documents Table
CREATE TABLE admin_documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_type ENUM('user', 'creator', 'admin') NOT NULL,
    target_id VARCHAR(50) NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    encrypted_filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    uploaded_by VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_target (target_type, target_id),
    INDEX idx_uploaded_by (uploaded_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 6. VIEWS
-- =====================================================================

-- USER views
USE user_base;

CREATE VIEW user_exam_overview AS
SELECT
    u.user_id,
    u.name AS user_name,
    u.name_in_certificate,
    u.email,
    pe.unique_exam_number,
    ur.unique_order_number,
    pe.payment_date,
    pe.amount_paid,
    le.exam_title,
    le.exam_description,
    le.channel_name,
    le.number_of_subscribers,
    ur.marks_obtained,
    ur.total_marks,
    ROUND((ur.marks_obtained/ur.total_marks)*100,2) AS percentage,
    ur.completed_at AS exam_completed_at,
    ur.certificate_url,
    CASE
        WHEN ur.marks_obtained IS NULL THEN 'Not Attempted'
        WHEN (ur.marks_obtained/ur.total_marks)*100>=90 THEN 'Excellent'
        WHEN (ur.marks_obtained/ur.total_marks)*100>=75 THEN 'Good'
        WHEN (ur.marks_obtained/ur.total_marks)*100>=60 THEN 'Average'
        ELSE 'Needs Improvement'
    END AS performance_category
FROM user_base.user u
LEFT JOIN exam.purchased_exams pe ON u.user_id = pe.user_id AND pe.payment_status = 'completed'
LEFT JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
LEFT JOIN user_base.user_result ur ON ur.unique_order_number = pe.unique_order_number
    AND pe.unique_exam_number = ur.unique_exam_number
    AND u.user_id = ur.user_id;

CREATE VIEW user_dashboard_stats AS
SELECT
    u.user_id,
    u.name,
    u.name_in_certificate,
    u.email,
    u.last_login,
    u.created_at,
    COUNT(DISTINCT pe.unique_exam_number) AS total_purchased_exams,
    COUNT(DISTINCT ur.unique_exam_number) AS total_completed_exams,
    SUM(pe.amount_paid) AS total_spent,
    AVG(ur.marks_obtained) AS average_marks,
    AVG((ur.marks_obtained/ur.total_marks)*100) AS average_percentage,
    SUM((ur.marks_obtained/ur.total_marks)*100 >= 90) AS excellent_count,
    SUM((ur.marks_obtained/ur.total_marks)*100 >= 75
        AND (ur.marks_obtained/ur.total_marks)*100 < 90) AS good_count,
    SUM((ur.marks_obtained/ur.total_marks)*100 >= 60
        AND (ur.marks_obtained/ur.total_marks)*100 < 75) AS average_count,
    SUM((ur.marks_obtained/ur.total_marks)*100 < 60) AS poor_count
FROM user_base.user u
LEFT JOIN exam.purchased_exams pe ON u.user_id = pe.user_id AND pe.payment_status = 'completed'
LEFT JOIN user_base.user_result ur ON u.user_id = ur.user_id
GROUP BY u.user_id, u.name, u.name_in_certificate, u.email, u.last_login, u.created_at;

-- CREATOR view
USE creator_base;

CREATE VIEW creator_payment_eligibility AS
SELECT 
    c.channel_id,
    c.creator_name,
    c.email,
    c.is_active AS creator_active,
    bi.id AS bank_info_id,
    bi.account_holder_name,
    bi.bank_name,
    bi.id_type,
    bi.country_code,
    bi.currency_code,
    bi.verification_status,
    bi.is_active AS bank_active,
    bi.is_frozen,
    bi.verified_at,
    CASE 
        WHEN c.is_active = 0 THEN 'Creator Account Disabled'
        WHEN bi.id IS NULL THEN 'No Bank Information'
        WHEN bi.verification_status = 0 THEN 'Bank Info Pending Verification'
        WHEN bi.verification_status = 2 THEN 'Bank Info Rejected'
        WHEN bi.verification_status = 3 THEN 'Bank Info Under Review'
        WHEN bi.is_active = 0 THEN 'Bank Account Disabled'
        WHEN bi.is_frozen = 1 THEN 'Bank Account Frozen'
        ELSE 'Payment Eligible'
    END AS payment_status,
    CASE 
        WHEN c.is_active = 1 AND bi.verification_status = 1 AND bi.is_active = 1 AND bi.is_frozen = 0 
        THEN TRUE ELSE FALSE 
    END AS can_receive_payment
FROM creators c
LEFT JOIN creator_bank_info bi ON c.channel_id = bi.channel_id;

-- EXAM view
USE exam;

CREATE VIEW exam_purchase_details AS
SELECT
    pe.id AS purchase_id,
    pe.unique_order_number,
    pe.user_id,
    pe.payment_id,
    pe.amount_paid,
    pe.payment_date,
    pe.payment_time,
    pe.payment_status,
    pe.payment_method,
    pe.razorpay_order_id,
    pe.razorpay_payment_id,
    le.unique_exam_number,
    le.channel_id,
    le.channel_name,
    le.number_of_subscribers,
    le.exam_title,
    le.exam_description,
    le.video_id,
    le.playlist_id,
    le.summary_path,
    pe.created_at AS purchase_created_at,
    le.created_at AS exam_created_at
FROM exam.purchased_exams pe
JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number;

-- QUERY views
USE query_base;

CREATE VIEW all_contact_queries AS
SELECT
    id,
    query_id,
    name,
    email,
    phone,
    subject,
    message,
    visitor_ip,
    resolved,
    resolved_at,
    resolved_by,
    submitted_at,
    updated_at,
    TIMESTAMPDIFF(HOUR, submitted_at, NOW()) AS hours_since_submission
FROM contact_us_queries
ORDER BY submitted_at DESC;

CREATE VIEW contact_pending_queries AS
SELECT
    id,
    query_id,
    name,
    email,
    phone,
    subject,
    message,
    visitor_ip,
    submitted_at,
    TIMESTAMPDIFF(HOUR, submitted_at, NOW()) AS hours_ago,
    TIMESTAMPDIFF(DAY, submitted_at, NOW()) AS days_ago
FROM contact_us_queries
WHERE resolved = 0
ORDER BY submitted_at ASC;

CREATE VIEW contact_resolved_queries AS
SELECT
    id,
    query_id,
    name,
    email,
    subject,
    submitted_at,
    resolved_at,
    resolved_by,
    TIMESTAMPDIFF(HOUR, submitted_at, resolved_at) AS hours_to_resolve,
    TIMESTAMPDIFF(DAY, submitted_at, resolved_at) AS days_to_resolve
FROM contact_us_queries
WHERE resolved = 1
ORDER BY resolved_at DESC;

CREATE VIEW contact_daily_stats AS
SELECT
    DATE(submitted_at) AS query_date,
    COUNT(*) AS total_queries,
    SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) AS resolved_queries,
    SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS pending_queries,
    COUNT(DISTINCT visitor_ip) AS unique_visitors,
    COUNT(DISTINCT email) AS unique_emails,
    ROUND(100.0 * SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS resolution_percentage
FROM contact_us_queries
GROUP BY DATE(submitted_at)
ORDER BY query_date DESC;

CREATE VIEW admin_resolution_stats AS
SELECT
    resolved_by,
    COUNT(*) AS resolved_count,
    ROUND(AVG(TIMESTAMPDIFF(HOUR, submitted_at, resolved_at)), 2) AS avg_hours_to_resolve,
    MIN(resolved_at) AS first_resolved_date,
    MAX(resolved_at) AS last_resolved_date
FROM contact_us_queries
WHERE resolved = 1 AND resolved_by IS NOT NULL
GROUP BY resolved_by
ORDER BY resolved_count DESC;

CREATE VIEW view_pending_creator_requests AS
SELECT 
    request_id,
    name,
    channel_name,
    subscriber_count,
    content_type,
    email,
    submitted_at,
    TIMESTAMPDIFF(HOUR, submitted_at, NOW()) AS hours_since_submission
FROM creator_join_requests
WHERE status = 'pending'
ORDER BY submitted_at DESC;

CREATE VIEW view_all_creator_requests AS
SELECT 
    request_id,
    name,
    channel_name,
    email,
    status,
    submitted_at,
    updated_at
FROM creator_join_requests
ORDER BY submitted_at DESC;

-- ADMIN views
USE admin_base;

CREATE VIEW admin_hierarchy AS
SELECT
    a.admin_id,
    a.name,
    a.email,
    a.designation,
    CASE a.designation
        WHEN 0 THEN 'Supreme'
        WHEN 1 THEN 'Chief'
        WHEN 2 THEN 'Major'
        WHEN 3 THEN 'Hero'
    END as designation_name,
    a.hoster_id,
    h.name as hoster_name,
    a.is_active,
    a.is_approved,
    a.date_joined,
    a.last_login
FROM admins a
LEFT JOIN admins h ON a.hoster_id = h.admin_id;

CREATE VIEW bank_verification_summary AS
SELECT
    bv.channel_id,
    c.creator_name,
    c.email,
    bv.verification_status,
    CASE bv.verification_status
        WHEN 0 THEN 'Pending'
        WHEN 1 THEN 'Verified'
        WHEN 2 THEN 'Rejected'
        WHEN 3 THEN 'Under Review'
    END as status_name,
    bv.verified_by,
    a.name as verified_by_name,
    bv.documents_verified,
    bv.id_verified,
    bv.bank_details_verified,
    bv.created_at,
    bv.updated_at
FROM bank_verifications bv
JOIN creator_base.creators c ON bv.channel_id = c.channel_id
LEFT JOIN admins a ON bv.verified_by = a.admin_id;

CREATE VIEW payout_summary AS
SELECT
    mp.id as payout_id,
    mp.payout_month,
    mp.total_creators,
    mp.total_amount,
    mp.platform_commission,
    mp.transfer_charges,
    mp.status,
    mp.processed_by,
    a.name as processed_by_name,
    mp.created_at,
    mp.completed_at
FROM monthly_payouts mp
JOIN admins a ON mp.processed_by = a.admin_id;

-- =====================================================================
-- 7. STORED PROCEDURES
-- =====================================================================

-- USER_BASE procedures
USE user_base;
DELIMITER //

CREATE PROCEDURE GetUserPurchasedExams(IN p_user_id VARCHAR(120))
BEGIN
    SELECT
        pe.unique_exam_number,
        pe.unique_order_number,
        pe.payment_date,
        pe.amount_paid,
        le.exam_title,
        le.exam_description,
        le.channel_name,
        le.thumbnail_image,
        ur.marks_obtained,
        ur.total_marks,
        ROUND((ur.marks_obtained/ur.total_marks)*100,2) AS percentage,
        ur.completed_at,
        ur.certificate_url,
        CASE WHEN ur.marks_obtained IS NULL THEN 'Not Attempted' ELSE 'Completed' END AS status
    FROM exam.purchased_exams pe
    JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
    LEFT JOIN user_base.user_result ur ON pe.unique_order_number = ur.unique_order_number
    WHERE pe.user_id = p_user_id AND pe.payment_status = 'completed'
    ORDER BY pe.payment_date DESC;
END //

CREATE PROCEDURE GetUserCompletedExams(IN p_user_id VARCHAR(120))
BEGIN
    SELECT
        ur.unique_exam_number,
        ur.marks_obtained,
        ur.total_marks,
        ROUND((ur.marks_obtained/ur.total_marks)*100,2) AS percentage,
        ur.completed_at,
        ur.attempt_number,
        ur.certificate_url,
        le.exam_title,
        le.channel_name,
        CASE
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 90 THEN 'Excellent'
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 75 THEN 'Good'
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 60 THEN 'Average'
            ELSE 'Needs Improvement'
        END AS performance_category
    FROM user_base.user_result ur
    JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
    WHERE ur.user_id = p_user_id
    ORDER BY ur.completed_at DESC;
END //

CREATE PROCEDURE RecordExamResult(
    IN p_unique_order_number VARCHAR(120),
    IN p_user_id VARCHAR(120),
    IN p_channel_id VARCHAR(120),
    IN p_unique_exam_number VARCHAR(120),
    IN p_payment_id VARCHAR(300),
    IN p_amount_paid DECIMAL(10,2),
    IN p_marks_obtained INT,
    IN p_total_marks INT
)
BEGIN
    INSERT INTO user_base.user_result (
        unique_order_number, user_id, channel_id, unique_exam_number,
        payment_date, payment_time, payment_id, amount_paid,
        marks_obtained, total_marks
    ) VALUES (
        p_unique_order_number, p_user_id, p_channel_id, p_unique_exam_number,
        CURDATE(), CURTIME(), p_payment_id, p_amount_paid,
        p_marks_obtained, p_total_marks
    );
END //

CREATE PROCEDURE UpdateUserOAuthTokens(
    IN p_user_id VARCHAR(120),
    IN p_oauth_token VARCHAR(1536),
    IN p_refresh_token VARCHAR(1536),
    IN p_client_id VARCHAR(765),
    IN p_client_secret VARCHAR(765),
    IN p_token_uri VARCHAR(765),
    IN p_token_expiry TIMESTAMP
)
BEGIN
    UPDATE user_base.user SET
        oauth_token = p_oauth_token,
        refresh_token = p_refresh_token,
        client_id = p_client_id,
        client_secret = p_client_secret,
        token_uri = p_token_uri,
        token_expiry = p_token_expiry,
        updated_at = NOW()
    WHERE user_id = p_user_id;
END //

CREATE PROCEDURE GetUserOAuthCredentials(IN p_user_id VARCHAR(120))
BEGIN
    SELECT
        oauth_token, refresh_token, client_id, client_secret,
        token_uri, token_expiry
    FROM user_base.user
    WHERE user_id = p_user_id;
END //
DELIMITER ;

-- EXAM procedures
USE exam;
DELIMITER //

CREATE PROCEDURE AddNewExam(
    IN p_unique_exam_number VARCHAR(120),
    IN p_channel_id VARCHAR(120),
    IN p_video_id VARCHAR(60),
    IN p_playlist_id VARCHAR(120),
    IN p_transcript_path VARCHAR(1500),
    IN p_summary_path VARCHAR(1500),
    IN p_channel_name VARCHAR(765),
    IN p_number_of_subscribers BIGINT,
    IN p_exam_title VARCHAR(1500),
    IN p_exam_description MEDIUMTEXT,
    IN p_exam_price DECIMAL(10,2),
    IN p_thumbnail_image VARCHAR(1500)
)
BEGIN
    INSERT INTO exam.listed_exams (
        unique_exam_number, channel_id, video_id, playlist_id,
        transcript_path, summary_path, channel_name, number_of_subscribers,
        exam_title, exam_description, exam_price, thumbnail_image
    ) VALUES (
        p_unique_exam_number, p_channel_id, p_video_id, p_playlist_id,
        p_transcript_path, p_summary_path, p_channel_name, p_number_of_subscribers,
        p_exam_title, p_exam_description, p_exam_price, p_thumbnail_image
    );
END //

CREATE PROCEDURE GetChannelSalesReport(
    IN p_channel_id VARCHAR(120),
    IN p_start_date DATE,
    IN p_end_date DATE
)
BEGIN
    SELECT
        le.exam_title,
        le.unique_exam_number,
        COUNT(pe.id) AS total_sales,
        SUM(pe.amount_paid) AS total_revenue,
        AVG(pe.amount_paid) AS avg_price
    FROM exam.listed_exams le
    LEFT JOIN exam.purchased_exams pe ON le.unique_exam_number = pe.unique_exam_number
        AND pe.payment_date BETWEEN p_start_date AND p_end_date
        AND pe.payment_status = 'completed'
    WHERE le.channel_id = p_channel_id
    GROUP BY le.unique_exam_number, le.exam_title
    ORDER BY total_revenue DESC;
END //

CREATE PROCEDURE SaveExamQuestions(
    IN p_unique_exam_number VARCHAR(120),
    IN p_questions_json LONGTEXT
)
BEGIN
    INSERT INTO exam.exam_questions (unique_exam_number, questions_json, created_at, updated_at)
    VALUES (p_unique_exam_number, p_questions_json, NOW(), NOW())
    ON DUPLICATE KEY UPDATE
        questions_json = VALUES(questions_json),
        updated_at = NOW();
END //
DELIMITER ;

-- CREATOR_BASE procedures
USE creator_base;
DELIMITER //

CREATE PROCEDURE UpdateCreatorOAuthTokens(
    IN p_channel_id VARCHAR(120),
    IN p_oauth_token VARCHAR(1536),
    IN p_refresh_token VARCHAR(1536),
    IN p_client_id VARCHAR(765),
    IN p_client_secret VARCHAR(765),
    IN p_token_uri VARCHAR(765),
    IN p_token_expiry TIMESTAMP
)
BEGIN
    UPDATE creator_base.creators SET
        oauth_token = p_oauth_token,
        refresh_token = p_refresh_token,
        client_id = p_client_id,
        client_secret = p_client_secret,
        token_uri = p_token_uri,
        token_expiry = p_token_expiry,
        oauth_connected = TRUE,
        updated_at = NOW()
    WHERE channel_id = p_channel_id;
END //

CREATE PROCEDURE GetCreatorOAuthCredentials(IN p_channel_id VARCHAR(120))
BEGIN
    SELECT
        oauth_token, refresh_token, client_id, client_secret,
        token_uri, token_expiry
    FROM creator_base.creators
    WHERE channel_id = p_channel_id;
END //

CREATE PROCEDURE StoreVideoData(
    IN p_channel_id VARCHAR(120),
    IN p_video_id VARCHAR(60),
    IN p_title VARCHAR(1500),
    IN p_video_description MEDIUMTEXT,
    IN p_thumbnail_image VARCHAR(1500),
    IN p_transcript_path VARCHAR(1500),
    IN p_summary_path VARCHAR(1500),
    IN p_duration_seconds INT
)
BEGIN
    INSERT INTO creator_base.videos (
        channel_id, video_id, title, video_description, thumbnail_image,
        transcript_path, summary_path, playlist_id, playlist_index, duration_seconds
    ) VALUES (
        p_channel_id, p_video_id, p_title, p_video_description, p_thumbnail_image,
        p_transcript_path, p_summary_path, NULL, NULL, p_duration_seconds
    )
    ON DUPLICATE KEY UPDATE
        title = VALUES(title),
        video_description = VALUES(video_description),
        thumbnail_image = VALUES(thumbnail_image),
        transcript_path = VALUES(transcript_path),
        summary_path = VALUES(summary_path),
        duration_seconds = VALUES(duration_seconds),
        updated_at = NOW();
END //

CREATE PROCEDURE StorePlaylistVideoData(
    IN p_channel_id VARCHAR(120),
    IN p_video_id VARCHAR(60),
    IN p_title VARCHAR(1500),
    IN p_video_description MEDIUMTEXT,
    IN p_thumbnail_image VARCHAR(1500),
    IN p_transcript_path VARCHAR(1500),
    IN p_summary_path VARCHAR(1500),
    IN p_playlist_id VARCHAR(120),
    IN p_playlist_index INT,
    IN p_duration_seconds INT
)
BEGIN
    DECLARE playlist_exists INT DEFAULT 0;
    SELECT COUNT(*) INTO playlist_exists 
    FROM creator_base.playlists 
    WHERE playlist_id = p_playlist_id;

    IF playlist_exists > 0 THEN
        INSERT INTO creator_base.videos (
            channel_id, video_id, title, video_description, thumbnail_image,
            transcript_path, summary_path, playlist_id, playlist_index, duration_seconds
        ) VALUES (
            p_channel_id, p_video_id, p_title, p_video_description, p_thumbnail_image,
            p_transcript_path, p_summary_path, p_playlist_id, p_playlist_index, p_duration_seconds
        )
        ON DUPLICATE KEY UPDATE
            title = VALUES(title),
            video_description = VALUES(video_description),
            thumbnail_image = VALUES(thumbnail_image),
            transcript_path = VALUES(transcript_path),
            summary_path = VALUES(summary_path),
            playlist_id = VALUES(playlist_id),
            playlist_index = VALUES(playlist_index),
            duration_seconds = VALUES(duration_seconds),
            updated_at = NOW();
    ELSE
        CALL StoreVideoData(
            p_channel_id, p_video_id, p_title, p_video_description, p_thumbnail_image,
            p_transcript_path, p_summary_path, p_duration_seconds
        );
    END IF;
END //

CREATE PROCEDURE GetVideoTranscriptPath(IN p_video_id VARCHAR(60))
BEGIN
    SELECT transcript_path, summary_path
    FROM creator_base.videos
    WHERE video_id = p_video_id;
END //

CREATE PROCEDURE GetPlaylistSummaryPath(IN p_playlist_id VARCHAR(120))
BEGIN
    SELECT summary_path
    FROM creator_base.playlists
    WHERE playlist_id = p_playlist_id;
END //

CREATE PROCEDURE UpdateVideoFilePaths(
    IN p_video_id VARCHAR(60),
    IN p_transcript_path VARCHAR(1500),
    IN p_summary_path VARCHAR(1500)
)
BEGIN
    UPDATE creator_base.videos SET
        transcript_path = p_transcript_path,
        summary_path = p_summary_path,
        updated_at = NOW()
    WHERE video_id = p_video_id;
END //

CREATE PROCEDURE UpdatePlaylistSummaryPath(
    IN p_playlist_id VARCHAR(120),
    IN p_summary_path VARCHAR(1500)
)
BEGIN
    UPDATE creator_base.playlists SET
        summary_path = p_summary_path,
        updated_at = NOW()
    WHERE playlist_id = p_playlist_id;
END //

CREATE PROCEDURE UpsertCreatorBankInfo(
    IN p_channel_id VARCHAR(120),
    IN p_account_holder_name VARCHAR(600),
    IN p_bank_name VARCHAR(600),
    IN p_branch_name VARCHAR(600),
    IN p_account_number VARCHAR(3000),
    IN p_account_type VARCHAR(60),
    IN p_ifsc_code VARCHAR(60),
    IN p_swift_code VARCHAR(60),
    IN p_iban VARCHAR(150),
    IN p_routing_number VARCHAR(60),
    IN p_sort_code VARCHAR(30),
    IN p_bsb_number VARCHAR(30),
    IN p_bank_address MEDIUMTEXT,
    IN p_account_holder_address MEDIUMTEXT,
    IN p_country_code VARCHAR(9),
    IN p_currency_code VARCHAR(9),
    IN p_id_type VARCHAR(60),
    IN p_id_number VARCHAR(3000),
    IN p_id_image_path VARCHAR(1500),
    IN p_bank_document_path VARCHAR(1500),
    IN p_created_by VARCHAR(150)
)
BEGIN
    INSERT INTO creator_bank_info (
        channel_id, account_holder_name, bank_name, branch_name, account_number, account_type,
        ifsc_code, swift_code, iban, routing_number, sort_code, bsb_number,
        bank_address, account_holder_address, country_code, currency_code,
        id_type, id_number, id_image_path, bank_document_path,
        created_by, verification_status
    ) VALUES (
        p_channel_id, p_account_holder_name, p_bank_name, p_branch_name, p_account_number, 
        CASE 
            WHEN p_account_type IN ('savings','current','business') THEN p_account_type
            ELSE 'savings'
        END,
        p_ifsc_code, p_swift_code, p_iban, p_routing_number, p_sort_code, p_bsb_number,
        p_bank_address, p_account_holder_address, p_country_code, p_currency_code,
        CASE 
            WHEN p_id_type IN ('aadhaar','pan','passport','driving_license','voter_id','other') THEN p_id_type
            ELSE 'other'
        END,
        p_id_number, p_id_image_path, p_bank_document_path,
        p_created_by, 0
    )
    ON DUPLICATE KEY UPDATE
        account_holder_name = VALUES(account_holder_name),
        bank_name = VALUES(bank_name),
        branch_name = VALUES(branch_name),
        account_number = VALUES(account_number),
        account_type = VALUES(account_type),
        ifsc_code = VALUES(ifsc_code),
        swift_code = VALUES(swift_code),
        iban = VALUES(iban),
        routing_number = VALUES(routing_number),
        sort_code = VALUES(sort_code),
        bsb_number = VALUES(bsb_number),
        bank_address = VALUES(bank_address),
        account_holder_address = VALUES(account_holder_address),
        country_code = VALUES(country_code),
        currency_code = VALUES(currency_code),
        id_type = VALUES(id_type),
        id_number = VALUES(id_number),
        id_image_path = VALUES(id_image_path),
        bank_document_path = VALUES(bank_document_path),
        updated_by = p_created_by,
        verification_status = 0,
        updated_at = NOW();
END //

CREATE PROCEDURE VerifyCreatorBankInfo(
    IN p_channel_id VARCHAR(120),
    IN p_verification_status TINYINT(1),
    IN p_verified_by VARCHAR(150),
    IN p_rejection_reason MEDIUMTEXT
)
BEGIN
    UPDATE creator_bank_info SET
        verification_status = p_verification_status,
        verified_by = p_verified_by,
        verified_at = CASE WHEN p_verification_status = 1 THEN NOW() ELSE NULL END,
        rejection_reason = CASE WHEN p_verification_status = 2 THEN p_rejection_reason ELSE NULL END,
        updated_by = p_verified_by,
        updated_at = NOW()
    WHERE channel_id = p_channel_id;
END //

CREATE PROCEDURE GetCreatorBankInfoForPayment(IN p_channel_id VARCHAR(120))
BEGIN
    SELECT 
        bi.*,
        c.creator_name,
        c.email,
        c.is_active AS creator_account_active
    FROM creator_bank_info bi
    JOIN creators c ON bi.channel_id = c.channel_id
    WHERE bi.channel_id = p_channel_id
      AND bi.verification_status = 1
      AND bi.is_active = 1
      AND bi.is_frozen = 0
      AND c.is_active = 1;
END //

-- NEW PROCEDURE: ToggleCreatorBankAccount
CREATE PROCEDURE ToggleCreatorBankAccount(
    IN p_account_id INT,
    IN p_channel_id VARCHAR(120)
)
BEGIN
    DECLARE v_current_active TINYINT DEFAULT NULL;
    DECLARE v_verification_status TINYINT;
    DECLARE v_is_frozen TINYINT;

    -- 1. Fetch details directly (no count(*))
    SELECT is_active, verification_status, is_frozen
    INTO v_current_active, v_verification_status, v_is_frozen
    FROM creator_base.creator_bank_info
    WHERE id = p_account_id AND channel_id = p_channel_id
    LIMIT 1;

    -- 2. Logic & Validation
    IF v_current_active IS NULL THEN
        -- Case: Account not found (SELECT INTO failed to set value)
        SELECT 
            0 AS success, 
            'Bank account not found or access denied.' AS message, 
            NULL as new_status,
            404 as http_code;
            
    ELSEIF v_verification_status != 1 THEN
        -- Case: Not verified
        SELECT 
            0 AS success, 
            'Only verified accounts can be activated.' AS message, 
            NULL as new_status,
            400 as http_code;
            
    ELSEIF v_is_frozen = 1 THEN
        -- Case: Frozen
        SELECT 
            0 AS success, 
            'This account is frozen and cannot be activated.' AS message, 
            NULL as new_status,
            400 as http_code;
            
    ELSE
        -- 3. Perform Updates
        IF v_current_active = 1 THEN
            -- [PROTECTION] Prevent deactivation of the only active account
            SELECT 
                0 AS success, 
                'This account is already active. To change, please activate a different account.' AS message, 
                1 AS new_status,
                400 as http_code;
        ELSE
            -- Action: Activate (Deactivate all others first)
            UPDATE creator_base.creator_bank_info
            SET is_active = 0, updated_by = p_channel_id, updated_at = NOW()
            WHERE channel_id = p_channel_id;

            UPDATE creator_base.creator_bank_info
            SET is_active = 1, updated_by = p_channel_id, updated_at = NOW()
            WHERE id = p_account_id;

            SELECT 
                1 AS success, 
                'Bank account activated successfully! Previous active account has been deactivated.' AS message, 
                1 AS new_status,
                200 as http_code;
        END IF;
    END IF;
END //

DELIMITER ;

-- QUERY_BASE procedures
USE query_base;
DELIMITER //

CREATE PROCEDURE SubmitCreatorJoinRequest(
    IN p_request_id VARCHAR(120),
    IN p_name VARCHAR(150),
    IN p_channel_name VARCHAR(765),
    IN p_channel_link VARCHAR(765),
    IN p_content_type VARCHAR(300),
    IN p_subscriber_count BIGINT,
    IN p_email VARCHAR(250),
    IN p_contact_number VARCHAR(60),
    IN p_visitor_ip VARCHAR(135)
)
BEGIN
    INSERT INTO creator_join_requests (
        request_id, name, channel_name, channel_link, 
        content_type, subscriber_count, email, 
        contact_number, visitor_ip, submitted_at
    ) VALUES (
        p_request_id, p_name, p_channel_name, p_channel_link,
        p_content_type, p_subscriber_count, p_email,
        p_contact_number, p_visitor_ip, NOW()
    );
END //
DELIMITER ;

-- ADMIN_BASE procedures
USE admin_base;
DELIMITER //

CREATE PROCEDURE LogAdminAction(
    IN p_admin_id VARCHAR(50),
    IN p_action_code VARCHAR(10),
    IN p_target_type VARCHAR(50),
    IN p_target_id VARCHAR(100),
    IN p_details TEXT,
    IN p_ip_address VARCHAR(45)
)
BEGIN
    INSERT INTO admin_logs (
        admin_id, action_code, target_type, target_id, details, ip_address
    ) VALUES (
        p_admin_id, p_action_code, p_target_type, p_target_id, p_details, p_ip_address
    );
END //

CREATE PROCEDURE GetAdminDashboardStats()
BEGIN
    SELECT
        (SELECT COUNT(*) FROM user_base.user WHERE is_active = 1) as active_users,
        (SELECT COUNT(*) FROM user_base.user) as total_users,
        (SELECT COUNT(*) FROM creator_base.creators WHERE is_active = 1) as active_creators,
        (SELECT COUNT(*) FROM creator_base.creators) as total_creators,
        (SELECT COUNT(*) FROM exam.listed_exams WHERE is_active = 1) as active_exams,
        (SELECT COUNT(*) FROM exam.purchased_exams WHERE payment_status = 'completed') as total_purchases,
        (SELECT COALESCE(SUM(amount_paid), 0) FROM exam.purchased_exams WHERE payment_status = 'completed') as total_revenue,
        (SELECT COUNT(*) FROM creator_base.creator_bank_info WHERE verification_status = 0) as pending_verifications;
END //

CREATE PROCEDURE ProcessMonthlyPayouts(
    IN p_admin_id VARCHAR(50),
    IN p_payout_month VARCHAR(7),
    IN p_commission_rate DECIMAL(5,4),  -- e.g., 0.4500 (45%)
    IN p_transfer_rate DECIMAL(5,4)     -- e.g., 0.0200 (2%)
)
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_channel_id VARCHAR(50);
    DECLARE v_gross_earnings DECIMAL(12,2);
    DECLARE v_commission DECIMAL(12,2);
    DECLARE v_transfer_charge DECIMAL(12,2);
    DECLARE v_net_payout DECIMAL(12,2);
    DECLARE v_payout_id INT;
    DECLARE v_total_creators INT DEFAULT 0;
    DECLARE v_total_amount DECIMAL(15,2) DEFAULT 0.00;
    DECLARE v_total_commission DECIMAL(15,2) DEFAULT 0.00;
    DECLARE v_total_charges DECIMAL(15,2) DEFAULT 0.00;

    DECLARE creator_cursor CURSOR FOR
        SELECT
            pe.channel_id,
            SUM(pe.amount_paid) as gross_earnings
        FROM exam.purchased_exams pe
        JOIN creator_base.creators c ON pe.channel_id = c.channel_id
        JOIN creator_base.creator_bank_info cbi ON c.channel_id = cbi.channel_id
        WHERE pe.payment_status = 'completed'
        AND DATE_FORMAT(pe.payment_date, '%Y-%m') = p_payout_month
        AND c.is_active = TRUE
        AND cbi.verification_status = 1
        AND cbi.is_active = 1
        AND cbi.is_frozen = 0
        GROUP BY pe.channel_id
        HAVING gross_earnings > 0;

    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    -- Create monthly payout record
    INSERT INTO monthly_payouts (payout_month, processed_by, status)
    VALUES (p_payout_month, p_admin_id, 'processing');

    SET v_payout_id = LAST_INSERT_ID();

    -- Open cursor and process each creator
    OPEN creator_cursor;

    read_loop: LOOP
        FETCH creator_cursor INTO v_channel_id, v_gross_earnings;
        IF done THEN
            LEAVE read_loop;
        END IF;

        -- Calculate deductions (using provided rates)
        SET v_commission = v_gross_earnings * p_commission_rate;
        SET v_transfer_charge = v_gross_earnings * p_transfer_rate;
        SET v_net_payout = v_gross_earnings - v_commission - v_transfer_charge;

        -- Insert payout detail
        INSERT INTO payout_details (
            payout_id, channel_id, gross_earnings, platform_commission,
            transfer_charge, net_payout, payment_status
        ) VALUES (
            v_payout_id, v_channel_id, v_gross_earnings, v_commission,
            v_transfer_charge, v_net_payout, 'completed'
        );

        -- Update totals
        SET v_total_creators = v_total_creators + 1;
        SET v_total_amount = v_total_amount + v_net_payout;
        SET v_total_commission = v_total_commission + v_commission;
        SET v_total_charges = v_total_charges + v_transfer_charge;
    END LOOP;

    CLOSE creator_cursor;

    -- Update monthly payout record with totals
    UPDATE monthly_payouts SET
        total_creators = v_total_creators,
        total_amount = v_total_amount,
        platform_commission = v_total_commission,
        transfer_charges = v_total_charges,
        status = 'completed',
        completed_at = NOW()
    WHERE id = v_payout_id;

    SELECT v_payout_id as payout_id, v_total_creators as creators_paid, v_total_amount as total_paid;
END //

CREATE PROCEDURE GetPlatformEarningsSummary(
    IN p_start_date DATE,
    IN p_end_date DATE,
    IN p_commission_rate DECIMAL(5,4),
    IN p_transfer_rate DECIMAL(5,4)
)
BEGIN
    SELECT
        COUNT(DISTINCT pe.channel_id) as total_creators,
        COUNT(DISTINCT pe.user_id) as total_users,
        COUNT(pe.id) as total_transactions,
        SUM(pe.amount_paid) as gross_revenue,
        SUM(pe.amount_paid) * p_commission_rate as platform_commission,
        SUM(pe.amount_paid) * p_transfer_rate as transfer_charges,
        SUM(pe.amount_paid) * (1 - p_commission_rate - p_transfer_rate) as creator_earnings
    FROM exam.purchased_exams pe
    WHERE pe.payment_date BETWEEN p_start_date AND p_end_date
    AND pe.payment_status = 'completed';
END //

CREATE PROCEDURE GetAdminActivitySummary(
    IN p_admin_id VARCHAR(50),
    IN p_start_date DATE,
    IN p_end_date DATE
)
BEGIN
    SELECT
        a.admin_id,
        a.name,
        a.designation,
        COUNT(l.id) as total_actions,
        COUNT(DISTINCT l.action_code) as unique_actions,
        COUNT(DISTINCT DATE(l.timestamp)) as active_days,
        MAX(l.timestamp) as last_action
    FROM admins a
    LEFT JOIN admin_logs l ON a.admin_id = l.admin_id
        AND DATE(l.timestamp) BETWEEN p_start_date AND p_end_date
    WHERE a.admin_id = p_admin_id
    GROUP BY a.admin_id, a.name, a.designation;
END //

CREATE PROCEDURE ApproveAndActivateBankAccount(
    IN p_account_id INT,
    IN p_admin_id VARCHAR(50)
)
BEGIN
    DECLARE v_channel_id VARCHAR(120);
    DECLARE v_current_status TINYINT;
    
    -- Start Transaction
    START TRANSACTION;
    
    -- 1. Fetch Info & Lock the target row
    SELECT cbi.verification_status, cbi.channel_id 
    INTO v_current_status, v_channel_id
    FROM creator_base.creator_bank_info AS cbi
    WHERE cbi.id = p_account_id 
    FOR UPDATE;
    
    -- Logic Checks
    IF v_channel_id IS NULL THEN
        ROLLBACK;
        SELECT 'NOT_FOUND' AS result_code;
    
    ELSEIF v_current_status NOT IN (0, 3) THEN
        ROLLBACK;
        SELECT 'INVALID_STATE' AS result_code, v_current_status AS status;
        
    ELSE
        -- 2. "CLEAN SLATE": Deactivate EVERY account for this channel
        -- We do not filter by ID here. We turn everything OFF first.
        UPDATE creator_base.creator_bank_info T
        SET T.is_active = 0, 
            T.updated_by = p_admin_id, 
            T.updated_at = NOW()
        WHERE T.channel_id = v_channel_id;
        
        -- 3. Activate ONLY the target account
        -- This overwrites the previous "0" with "1" for just this row.
        UPDATE creator_base.creator_bank_info T
        SET T.verification_status = 1,
            T.is_active = 1,
            T.verified_by = p_admin_id,
            T.verified_at = NOW(),
            T.rejection_reason = NULL,
            T.updated_by = p_admin_id,
            T.updated_at = NOW()
        WHERE T.id = p_account_id;
        
        COMMIT;
        SELECT 'SUCCESS' AS result_code;
    END IF;
END //

-- ROBUST VERSION: ProcessAdminApproval (Added V2)
CREATE PROCEDURE ProcessAdminApproval(
    IN p_request_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    IN p_approver_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    IN p_new_password_hash VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    IN p_designation TINYINT,
    IN p_limit INT,
    IN p_prefix VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
)
BEGIN
    -- Declare variables with both Charset and Collation
    DECLARE v_email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    DECLARE v_name VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    DECLARE v_contact VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    DECLARE v_current_count INT;
    DECLARE v_next_num INT;
    DECLARE v_new_admin_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    
    START TRANSACTION;
    
    -- 1. Fetch Request Details
    SELECT email, name, contact_number 
    INTO v_email, v_name, v_contact
    FROM admin_base.registration_requests 
    WHERE request_id = p_request_id AND status = 'pending'
    FOR UPDATE;
    
    IF v_email IS NULL THEN
        ROLLBACK;
        SELECT 'REQ_NOT_FOUND' AS result_code;
    ELSE
        -- 2. Check Designation Limits
        SELECT COUNT(*) INTO v_current_count 
        FROM admin_base.admins 
        WHERE designation = p_designation;
        
        IF v_current_count >= p_limit THEN
            ROLLBACK;
            SELECT 'LIMIT_EXCEEDED' AS result_code;
        ELSE
            -- 3. Generate Unique Admin ID
            SELECT IFNULL(MAX(CAST(SUBSTRING_INDEX(admin_id, '_', -1) AS UNSIGNED)), 0) + 1 
            INTO v_next_num
            FROM admin_base.admins 
            WHERE designation = p_designation 
              AND admin_id LIKE CONCAT('ADM_', p_prefix, '_%') COLLATE utf8mb4_unicode_ci
            FOR UPDATE;
            
            SET v_new_admin_id = CONCAT('ADM_', p_prefix, '_', LPAD(v_next_num, 3, '0'));
            
            -- 4. Insert New Admin Account
            INSERT INTO admin_base.admins (
                admin_id, email, contact_number, password_hash, designation, 
                name, hoster_id, is_active, is_approved, date_joined, created_at, updated_at
            ) VALUES (
                v_new_admin_id, v_email, v_contact, p_new_password_hash, p_designation,
                v_name, p_approver_id, 1, 1, NOW(), NOW(), NOW()
            );
            
            -- 5. Update Registration Request Status
            UPDATE admin_base.registration_requests
            SET status = 'approved', 
                approved_by = p_approver_id, 
                approved_at = NOW(),
                updated_at = NOW()
            WHERE request_id = p_request_id;
            
            COMMIT;
            
            -- Return success data
            SELECT 'SUCCESS' AS result_code, v_new_admin_id AS new_admin_id, v_email AS email, v_name AS name;
        END IF;
    END IF;
END //

-- PROCEDURE: RejectRegistrationRequest (Added V2)
CREATE PROCEDURE RejectRegistrationRequest(
    IN p_request_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    IN p_admin_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    IN p_reason TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
)
BEGIN
    DECLARE v_email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    DECLARE v_name VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    
    START TRANSACTION;
    
    -- 1. Check existence AND Lock row
    SELECT email, name INTO v_email, v_name
    FROM admin_base.registration_requests
    WHERE request_id = p_request_id AND status = 'pending'
    FOR UPDATE;
    
    IF v_email IS NULL THEN
        ROLLBACK;
        SELECT 'NOT_FOUND' AS result_code;
    ELSE
        -- 2. Update Status to Rejected
        -- WE USE 'approved_by' because your schema uses it for both actions
        UPDATE admin_base.registration_requests
        SET status = 'rejected',
            rejection_reason = p_reason,
            approved_by = p_admin_id,  -- Records WHO rejected it
            approved_at = NOW(),       -- Records WHEN
            updated_at = NOW()
        WHERE request_id = p_request_id;
        
        COMMIT;
        
        -- 3. Return Data for Emailing
        SELECT 'SUCCESS' AS result_code, v_email AS email, v_name AS name;
    END IF;
END //

-- PROCEDURE: GetFullAdminDashboardData (Added V2)
CREATE PROCEDURE GetFullAdminDashboardData(
    IN p_is_supreme BOOLEAN
)
BEGIN
    -- 1. BASIC STATS (First Result Set)
    SELECT
        (SELECT COUNT(*) FROM user_base.user WHERE is_active = 1) as active_users,
        (SELECT COUNT(*) FROM user_base.user) as total_users,
        (SELECT COUNT(*) FROM creator_base.creators WHERE is_active = 1) as active_creators,
        (SELECT COUNT(*) FROM creator_base.creators) as total_creators,
        (SELECT COUNT(*) FROM exam.listed_exams WHERE is_active = 1) as active_exams,
        (SELECT COUNT(*) FROM exam.purchased_exams WHERE payment_status = 'completed') as total_purchases,
        (SELECT COALESCE(SUM(amount_paid), 0) FROM exam.purchased_exams WHERE payment_status = 'completed') as total_revenue,
        (SELECT COUNT(*) FROM creator_base.creator_bank_info WHERE verification_status = 0) as pending_verifications;

    -- 2. MONTHLY SALES GRAPH (Second Result Set)
    SELECT
        COUNT(id) as monthly_sales,
        COALESCE(SUM(amount_paid), 0.00) as monthly_revenue
    FROM exam.purchased_exams
    WHERE payment_status = 'completed'
    AND payment_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
    AND payment_date <= LAST_DAY(CURDATE());

    -- 3. RECENT LOGS (Third Result Set)
    SELECT l.id, l.admin_id, l.action_code, l.target_type, l.target_id, l.details, l.timestamp,
            a.name as admin_name
    FROM admin_base.admin_logs l
    LEFT JOIN admin_base.admins a ON l.admin_id = a.admin_id
    ORDER BY l.timestamp DESC
    LIMIT 10;

    -- 4. PENDING REGISTRATIONS (Fourth Result Set - Only if Supreme)
    IF p_is_supreme THEN
        SELECT COUNT(*) as pending_registrations FROM admin_base.registration_requests WHERE status = 'pending';
    ELSE
        SELECT 0 as pending_registrations;
    END IF;
END //

-- PROCEDURE: GetAdminEarningAnalysis (Added V2)
CREATE PROCEDURE GetAdminEarningAnalysis(
    IN p_start_date DATE,
    IN p_end_date DATE
)
BEGIN
    -- 1. OVERALL TOTALS (For the selected period)
    SELECT 
        COALESCE(SUM(amount_paid), 0) as total_revenue,
        COUNT(*) as total_transactions,
        COALESCE(AVG(amount_paid), 0) as avg_order_value,
        COUNT(DISTINCT user_id) as unique_buyers
    FROM exam.purchased_exams 
    WHERE payment_status = 'completed'
      AND DATE(payment_date) BETWEEN p_start_date AND p_end_date;

    -- 2. REVENUE TREND (Daily breakdown for the selected period)
    SELECT 
        DATE_FORMAT(payment_date, '%Y-%m-%d') as date_label,
        COALESCE(SUM(amount_paid), 0) as daily_revenue,
        COUNT(id) as daily_sales
    FROM exam.purchased_exams
    WHERE payment_status = 'completed'
      AND DATE(payment_date) BETWEEN p_start_date AND p_end_date
    GROUP BY DATE_FORMAT(payment_date, '%Y-%m-%d')
    ORDER BY date_label ASC;

    -- 3. TOP PERFORMING CREATORS (Leaderboard for selected period)
    SELECT 
        c.creator_name,
        c.email,
        c.channel_id,
        COUNT(pe.id) as sales_count,
        COALESCE(SUM(pe.amount_paid), 0) as total_revenue
    FROM exam.purchased_exams pe
    JOIN creator_base.creators c ON pe.channel_id = c.channel_id
    WHERE pe.payment_status = 'completed'
      AND DATE(pe.payment_date) BETWEEN p_start_date AND p_end_date
    GROUP BY c.channel_id, c.creator_name, c.email
    ORDER BY total_revenue DESC
    LIMIT 10;

    -- 4. RECENT TRANSACTIONS (Last 20 in this period)
    SELECT 
        pe.unique_order_number,
        pe.amount_paid,
        pe.payment_date,
        u.name as user_name,
        u.email as user_email
    FROM exam.purchased_exams pe
    LEFT JOIN user_base.user u ON pe.user_id = u.user_id
    WHERE pe.payment_status = 'completed'
      AND DATE(pe.payment_date) BETWEEN p_start_date AND p_end_date
    ORDER BY pe.payment_date DESC
    LIMIT 20;

END //

DELIMITER ;

COMMIT;


-- =====================================================================
-- UPGRADE v4.0: DATABASE-BASED OTP AND PASSWORD RESET TOKENS
-- =====================================================================
-- Added by: System Upgrade
-- Date: 2024
-- Purpose: Replace file-based OTP/token storage with database tables
--          for multi-instance compatibility (Google Cloud Run ready)
-- =====================================================================

-- Table for storing OTP codes for admins, creators, and users
CREATE TABLE IF NOT EXISTS admin_base.otp_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_type ENUM('admin', 'creator', 'user') NOT NULL COMMENT 'Type of user: admin, creator, or user',
    email VARCHAR(255) NOT NULL COMMENT 'Email address of the user',
    otp_code VARCHAR(10) NOT NULL COMMENT 'The OTP code (6 digits)',
    purpose VARCHAR(50) DEFAULT 'login' COMMENT 'Purpose: login, registration, first_time_setup, etc',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When the OTP was created',
    expires_at TIMESTAMP NOT NULL COMMENT 'When the OTP expires',
    verified BOOLEAN DEFAULT FALSE COMMENT 'Whether OTP has been verified',
    ip_address VARCHAR(45) COMMENT 'IP address that requested the OTP',
    
    INDEX idx_email_type (email, user_type),
    INDEX idx_expires (expires_at),
    INDEX idx_verified (verified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores OTP codes for email verification (replaces file storage)';


-- Table for storing password reset tokens
CREATE TABLE IF NOT EXISTS admin_base.password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_type ENUM('admin', 'creator', 'user') NOT NULL COMMENT 'Type of user',
    email VARCHAR(255) NOT NULL COMMENT 'Email address of the user',
    token_hash VARCHAR(255) NOT NULL UNIQUE COMMENT 'Hashed reset token for security',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When the token was created',
    expires_at TIMESTAMP NOT NULL COMMENT 'When the token expires',
    used BOOLEAN DEFAULT FALSE COMMENT 'Whether token has been used',
    ip_address VARCHAR(45) COMMENT 'IP address that requested the reset',
    
    INDEX idx_token_hash (token_hash),
    INDEX idx_email_type (email, user_type),
    INDEX idx_expires (expires_at),
    INDEX idx_used (used)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores password reset tokens (replaces file storage)';


-- Table for tracking failed login attempts
CREATE TABLE IF NOT EXISTS admin_base.failed_login_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL COMMENT 'Email address attempting to login',
    user_type ENUM('admin', 'creator', 'user') NOT NULL COMMENT 'Type of user account',
    attempts INT NOT NULL DEFAULT 1 COMMENT 'Number of failed attempts',
    last_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last failed login attempt time',
    ip_address VARCHAR(45) COMMENT 'IP address of the failed attempt',

    UNIQUE KEY unique_email_type (email, user_type),
    INDEX idx_last_attempt (last_attempt_at),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tracks failed login attempts for security monitoring';


-- Table for login lockouts (after exceeding failed attempts)
CREATE TABLE IF NOT EXISTS admin_base.login_lockouts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL COMMENT 'Email address that is locked',
    user_type ENUM('admin', 'creator', 'user') NOT NULL COMMENT 'Type of user account',
    locked_until TIMESTAMP NOT NULL COMMENT 'When the lockout expires',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When the lockout was created',
    ip_address VARCHAR(45) COMMENT 'IP address that triggered the lockout',

    INDEX idx_email_type (email, user_type),
    INDEX idx_locked_until (locked_until),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores temporary login lockouts for accounts with too many failed attempts';


-- Cleanup procedure for expired tokens (run periodically via cron)
DELIMITER //

DROP PROCEDURE IF EXISTS admin_base.CleanupExpiredTokens //

CREATE PROCEDURE admin_base.CleanupExpiredTokens()
BEGIN
    DECLARE deleted_otps INT DEFAULT 0;
    DECLARE deleted_tokens INT DEFAULT 0;
    
    -- Delete expired OTPs
    DELETE FROM admin_base.otp_tokens 
    WHERE expires_at < NOW();
    SET deleted_otps = ROW_COUNT();
    
    -- Delete expired password reset tokens
    DELETE FROM admin_base.password_reset_tokens 
    WHERE expires_at < NOW();
    SET deleted_tokens = ROW_COUNT();
    
    -- Also delete used tokens older than 24 hours
    DELETE FROM admin_base.otp_tokens
    WHERE verified = TRUE AND created_at < DATE_SUB(NOW(), INTERVAL 24 HOUR);

    DELETE FROM admin_base.password_reset_tokens
    WHERE used = TRUE AND created_at < DATE_SUB(NOW(), INTERVAL 24 HOUR);

    -- Delete expired login lockouts
    DELETE FROM admin_base.login_lockouts
    WHERE locked_until < NOW();

    -- Delete old failed login attempts (older than 7 days)
    DELETE FROM admin_base.failed_login_attempts
    WHERE last_attempt_at < DATE_SUB(NOW(), INTERVAL 7 DAY);

    SELECT
        'Cleanup completed' AS status,
        deleted_otps AS otps_deleted,
        deleted_tokens AS tokens_deleted,
        (SELECT COUNT(*) FROM admin_base.otp_tokens) AS remaining_otps,
        (SELECT COUNT(*) FROM admin_base.password_reset_tokens) AS remaining_reset_tokens,
        (SELECT COUNT(*) FROM admin_base.login_lockouts) AS remaining_lockouts,
        (SELECT COUNT(*) FROM admin_base.failed_login_attempts) AS remaining_failed_attempts;
END //

DELIMITER ;

-- =====================================================================
-- END OF UPGRADE v4.0
-- =====================================================================


-- =====================================================================
-- UPGRADE v5.0: FEATURED EXAMS & PROMOTIONAL CAROUSEL SYSTEM
-- =====================================================================
-- Added by: System Upgrade
-- Date: 2025-12-31
-- Purpose: Add admin-managed featured exams for homepage carousel
-- =====================================================================

-- Table for admin-selected featured exams (5 slots)
CREATE TABLE IF NOT EXISTS admin_base.admin_featured_exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL COMMENT 'Reference to exam.listed_exams.id',
    display_order INT NOT NULL COMMENT 'Display order (1-5)',
    is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether this featured exam is active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When exam was added to featured',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
    created_by INT NOT NULL COMMENT 'Admin user ID who added this',

    UNIQUE KEY unique_exam_id (exam_id),
    UNIQUE KEY unique_display_order (display_order),
    FOREIGN KEY (exam_id) REFERENCES exam.listed_exams(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES admin_base.admins(id) ON DELETE RESTRICT,
    INDEX idx_active (is_active),
    INDEX idx_order (display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores 5 admin-selected featured exams for homepage carousel';


-- Table for caching promotional exams display
CREATE TABLE IF NOT EXISTS admin_base.promotional_exams_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL COMMENT 'Reference to exam.listed_exams.id',
    display_order INT NOT NULL COMMENT 'Display order in carousel (1-10)',
    source VARCHAR(20) NOT NULL COMMENT 'Source: featured or random',
    cache_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When this cache entry was created',

    FOREIGN KEY (exam_id) REFERENCES exam.listed_exams(id) ON DELETE CASCADE,
    INDEX idx_display_order (display_order),
    INDEX idx_cache_timestamp (cache_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Cache for 10 promotional exams shown on homepage (5 featured + 5 random)';


-- =====================================================================
-- END OF UPGRADE v5.0
-- =====================================================================


-- =====================================================================
-- UPGRADE v5.1: Profile Picture & Certificate Name Enhancement
-- =====================================================================
-- Date: 2026-01-01
-- Changes:
--   1. Added profile_picture column to user_base.user table
--   2. Already includes name_in_certificate column for certificates
--   3. Profile picture URL from Google OAuth stored in database
--   4. Certificate name is required during user onboarding
-- =====================================================================

-- NOTE: The following columns are already present in the user table above:
--   - profile_picture VARCHAR(1500) - Line 47
--   - name_in_certificate VARCHAR(600) NULL DEFAULT NULL - Line 34
--
-- Migration script: migration_add_featured_exams.sql
--   - Uses stored procedure for conditional column addition
--   - Safe to run multiple times (idempotent)
--   - Adds profile_picture only if it doesn't exist
-- =====================================================================

