-- =====================================================================
-- YOUCERT: TiDB Cloud Compatible Schema (V16.0)
-- Databases: user_base, creator_base, exam, query_base, admin_base
-- NOTE: Stored procedures REMOVED for TiDB Cloud Serverless compatibility.
--       All procedure logic has been moved to Python application layer.
--       Run this file ONCE on your TiDB Cloud Serverless cluster.
-- TiDB Docs: https://docs.pingcap.com/tidbcloud/
-- =====================================================================

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
-- CRITICAL FIX: Temporarily disable foreign key checks so we can safely
-- drop entire databases without having to drop dependent tables first,
-- preventing "Unknown Database" errors on completely fresh clusters.
-- =====================================================================
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- TIDB FIX: Enable CHECK constraints (disabled by default in TiDB)
-- Without this, all CONSTRAINT chk_* CHECK(...) clauses are silently ignored.
-- See: https://docs.pingcap.com/tidb/stable/constraints/#check-constraints
-- =====================================================================
SET SESSION tidb_enable_check_constraint = ON;

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
    totp_secret VARCHAR(100) NULL DEFAULT NULL COMMENT 'TOTP secret for authenticator app (base32)',
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
FROM contact_us_queries;
-- NOTE (TiDB): ORDER BY removed from view definition. Apply ORDER BY when querying the view instead.

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
WHERE resolved = 0;
-- NOTE (TiDB): ORDER BY removed from view definition. Apply ORDER BY when querying.

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
WHERE resolved = 1;
-- NOTE (TiDB): ORDER BY removed from view definition. Apply ORDER BY when querying.

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
GROUP BY DATE(submitted_at);
-- NOTE (TiDB): ORDER BY removed from view definition.

CREATE VIEW admin_resolution_stats AS
SELECT
    resolved_by,
    COUNT(*) AS resolved_count,
    ROUND(AVG(TIMESTAMPDIFF(HOUR, submitted_at, resolved_at)), 2) AS avg_hours_to_resolve,
    MIN(resolved_at) AS first_resolved_date,
    MAX(resolved_at) AS last_resolved_date
FROM contact_us_queries
WHERE resolved = 1 AND resolved_by IS NOT NULL
GROUP BY resolved_by;
-- NOTE (TiDB): ORDER BY removed from view definition.

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
WHERE status = 'pending';
-- NOTE (TiDB): ORDER BY removed from view definition.

CREATE VIEW view_all_creator_requests AS
SELECT 
    request_id,
    name,
    channel_name,
    email,
    status,
    submitted_at,
    updated_at
FROM creator_join_requests;
-- NOTE (TiDB): ORDER BY removed from view definition.

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
-- UPGRADE v4.0: OTP and Password Reset Tokens
-- =====================================================================
USE admin_base;

-- =====================================================================
-- UPGRADE v4.0: DATABASE-BASED OTP AND PASSWORD RESET TOKENS
-- =====================================================================
-- Added by: System Upgrade
-- Date: 2024
-- Purpose: Replace file-based OTP/token storage with database tables
--          for multi-instance compatibility (Google Cloud Run ready)
-- =====================================================================

-- Table for storing OTP codes for admins, creators, and users
CREATE TABLE IF NOT EXISTS otp_tokens (
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
CREATE TABLE IF NOT EXISTS password_reset_tokens (
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
CREATE TABLE IF NOT EXISTS failed_login_attempts (
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
CREATE TABLE IF NOT EXISTS login_lockouts (
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
CREATE TABLE IF NOT EXISTS admin_featured_exams (
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
    FOREIGN KEY (created_by) REFERENCES admins(id) ON DELETE RESTRICT,
    INDEX idx_active (is_active),
    INDEX idx_order (display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores 5 admin-selected featured exams for homepage carousel';


-- Table for caching promotional exams display
CREATE TABLE IF NOT EXISTS promotional_exams_cache (
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
-- END
-- RESTORE FOREIGN KEY CHECKS
-- =====================================================================
SET FOREIGN_KEY_CHECKS = 1;

