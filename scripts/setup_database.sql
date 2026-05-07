-- ==============================================================
-- PUCP Cloud Orchestrator - MariaDB Schema v2
-- Database: pucp_orchestrator
-- Adds: users (RBAC), images, zones
-- ==============================================================

CREATE DATABASE IF NOT EXISTS pucp_orchestrator
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE pucp_orchestrator;

CREATE USER IF NOT EXISTS 'orchestrator'@'localhost'
    IDENTIFIED BY 'PucpCloud2026!';

GRANT ALL PRIVILEGES ON pucp_orchestrator.* TO 'orchestrator'@'localhost';
FLUSH PRIVILEGES;

-- =============================================================
-- Users table (RBAC)
-- =============================================================
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(64)  PRIMARY KEY,
    username        VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(50)  DEFAULT 'user',
    email           VARCHAR(255) DEFAULT NULL,
    is_active       TINYINT      DEFAULT 1,
    max_vcpus       INT          DEFAULT 16,
    max_ram_mb      INT          DEFAULT 16384,
    max_slices      INT          DEFAULT 10,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Slices table
-- =============================================================
CREATE TABLE IF NOT EXISTS slices (
    id              VARCHAR(64)  PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    topology        VARCHAR(50)  NOT NULL,
    num_vms         INT          NOT NULL,
    vcpus_per_vm    INT          DEFAULT 1,
    ram_mb_per_vm   INT          DEFAULT 512,
    disk_gb_per_vm  INT          DEFAULT 2,
    vlan_id         INT          DEFAULT NULL,
    subnet          VARCHAR(50)  DEFAULT NULL,
    enable_dhcp     TINYINT      DEFAULT 0,
    enable_internet TINYINT      DEFAULT 0,
    status          VARCHAR(50)  DEFAULT 'pending',
    created_by      VARCHAR(255) DEFAULT 'admin',
    error_message   TEXT         DEFAULT NULL,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- =============================================================
-- VMs table
-- =============================================================
CREATE TABLE IF NOT EXISTS vms (
    id              VARCHAR(64)  PRIMARY KEY,
    slice_id        VARCHAR(64)  NOT NULL,
    name            VARCHAR(255) NOT NULL,
    `index`         INT          NOT NULL,
    host_ip         VARCHAR(50)  DEFAULT NULL,
    vcpus           INT          DEFAULT 1,
    ram_mb          INT          DEFAULT 512,
    disk_gb         INT          DEFAULT 2,
    ip_address      VARCHAR(50)  DEFAULT NULL,
    mac_address     VARCHAR(50)  DEFAULT NULL,
    vnc_port        INT          DEFAULT NULL,
    vnc_token       VARCHAR(50)  DEFAULT NULL,
    tap_interface   VARCHAR(100) DEFAULT NULL,
    qemu_pid        INT          DEFAULT NULL,
    status          VARCHAR(50)  DEFAULT 'pending',
    error_message   TEXT         DEFAULT NULL,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (slice_id) REFERENCES slices(id) ON DELETE CASCADE
);

-- =============================================================
-- Hosts table
-- =============================================================
CREATE TABLE IF NOT EXISTS hosts (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    hostname          VARCHAR(255) UNIQUE NOT NULL,
    ip                VARCHAR(50)  UNIQUE NOT NULL,
    role              VARCHAR(50)  DEFAULT 'worker',
    zone_id           VARCHAR(64)  DEFAULT NULL,
    total_vcpus       INT          DEFAULT 8,
    total_ram_mb      INT          DEFAULT 8192,
    total_disk_gb     INT          DEFAULT 100,
    available_vcpus   INT          DEFAULT 8,
    available_ram_mb  INT          DEFAULT 8192,
    available_disk_gb INT          DEFAULT 100,
    is_active         TINYINT      DEFAULT 1
);

-- =============================================================
-- Availability zones table
-- =============================================================
CREATE TABLE IF NOT EXISTS zones (
    id          VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(255) UNIQUE NOT NULL,
    description TEXT DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Images table
-- =============================================================
CREATE TABLE IF NOT EXISTS images (
    id          VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    filename    VARCHAR(255) NOT NULL,
    path        VARCHAR(512) NOT NULL,
    format      VARCHAR(20)  DEFAULT 'qcow2',
    sha256      VARCHAR(128) DEFAULT NULL,
    size_gb     INT          DEFAULT 2,
    uploaded_by VARCHAR(255) DEFAULT 'admin',
    is_active   TINYINT      DEFAULT 1,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Template table (export/import plantillas)
-- =============================================================
CREATE TABLE IF NOT EXISTS templates (
    id          VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT DEFAULT NULL,
    config_json TEXT NOT NULL,
    created_by  VARCHAR(255) DEFAULT 'admin',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Logs table
-- =============================================================
CREATE TABLE IF NOT EXISTS logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    slice_id    VARCHAR(64)  DEFAULT NULL,
    user_id     VARCHAR(64)  DEFAULT NULL,
    module      VARCHAR(100) NOT NULL,
    level       VARCHAR(20)  DEFAULT 'INFO',
    message     TEXT         NOT NULL,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Orphan resources table (cleanup tracking)
-- =============================================================
CREATE TABLE IF NOT EXISTS orphan_resources (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    resource_type VARCHAR(50)  NOT NULL,
    resource_name VARCHAR(255) NOT NULL,
    host_ip       VARCHAR(50)  DEFAULT NULL,
    slice_id      VARCHAR(64)  DEFAULT NULL,
    details       TEXT         DEFAULT NULL,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- Default data: admin user (password: admin123)
-- Password hash: SHA256('admin123' + secret)
-- =============================================================
INSERT IGNORE INTO users (id, username, password_hash, role, is_active)
VALUES ('u00001', 'admin', 'fd7ac9aa0c7a52a6b1f2ca549f6babc8b45d0b5278c4a3ef33ee24fae4edb904', 'admin', 1);

INSERT IGNORE INTO users (id, username, password_hash, role, is_active)
VALUES ('u00002', 'operador', '1a7585b3eb0cb5647d19b635ee984589516ec0f334b28f8ad513c18f71966d0e', 'operator', 1);

INSERT IGNORE INTO users (id, username, password_hash, role, is_active)
VALUES ('u00003', 'usuario', '17cdf11d42a641d930d1fd4bab0ee68964556d3937d66ad5120a65e21b3a296e', 'user', 1);

INSERT IGNORE INTO zones (id, name, description)
VALUES ('zone1', 'Zona Principal', 'Zona de disponibilidad por defecto');

-- Link all hosts to the default zone
UPDATE hosts SET zone_id = 'zone1' WHERE zone_id IS NULL;

SELECT 'Database setup complete (v2 - RBAC)' AS status;
