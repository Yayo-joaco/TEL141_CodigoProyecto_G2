-- ==============================================================
-- PUCP Cloud Orchestrator - MariaDB Schema
-- Database: pucp_orchestrator
-- ==============================================================

CREATE DATABASE IF NOT EXISTS pucp_orchestrator
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE pucp_orchestrator;

CREATE USER IF NOT EXISTS 'orchestrator'@'localhost'
    IDENTIFIED BY 'PucpCloud2026!';

GRANT ALL PRIVILEGES ON pucp_orchestrator.* TO 'orchestrator'@'localhost';
FLUSH PRIVILEGES;

-- Slices table
CREATE TABLE IF NOT EXISTS slices (
    id          VARCHAR(64)  PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    topology    VARCHAR(50)  NOT NULL,
    num_vms     INT          NOT NULL,
    vcpus_per_vm INT         DEFAULT 1,
    ram_mb_per_vm INT        DEFAULT 512,
    disk_gb_per_vm INT       DEFAULT 2,
    vlan_id     INT          DEFAULT NULL,
    subnet      VARCHAR(50)  DEFAULT NULL,
    enable_dhcp TINYINT      DEFAULT 0,
    enable_internet TINYINT  DEFAULT 0,
    status      VARCHAR(50)  DEFAULT 'pending',
    created_by  VARCHAR(255) DEFAULT 'admin',
    error_message TEXT       DEFAULT NULL,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- VMs table
CREATE TABLE IF NOT EXISTS vms (
    id            VARCHAR(64)  PRIMARY KEY,
    slice_id      VARCHAR(64)  NOT NULL,
    name          VARCHAR(255) NOT NULL,
    `index`       INT          NOT NULL,
    host_ip       VARCHAR(50)  DEFAULT NULL,
    vcpus         INT          DEFAULT 1,
    ram_mb        INT          DEFAULT 512,
    disk_gb       INT          DEFAULT 2,
    ip_address    VARCHAR(50)  DEFAULT NULL,
    mac_address   VARCHAR(50)  DEFAULT NULL,
    vnc_port      INT          DEFAULT NULL,
    vnc_token     VARCHAR(50)  DEFAULT NULL,
    tap_interface VARCHAR(100) DEFAULT NULL,
    qemu_pid      INT          DEFAULT NULL,
    status        VARCHAR(50)  DEFAULT 'pending',
    error_message TEXT         DEFAULT NULL,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (slice_id) REFERENCES slices(id) ON DELETE CASCADE
);

-- Hosts table
CREATE TABLE IF NOT EXISTS hosts (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    hostname        VARCHAR(255) UNIQUE NOT NULL,
    ip              VARCHAR(50)  UNIQUE NOT NULL,
    role            VARCHAR(50)  DEFAULT 'worker',
    total_vcpus     INT          DEFAULT 8,
    total_ram_mb    INT          DEFAULT 8192,
    total_disk_gb   INT          DEFAULT 100,
    available_vcpus INT          DEFAULT 8,
    available_ram_mb INT         DEFAULT 8192,
    available_disk_gb INT        DEFAULT 100,
    is_active       TINYINT      DEFAULT 1
);

-- Logs table
CREATE TABLE IF NOT EXISTS logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    slice_id    VARCHAR(64)  DEFAULT NULL,
    module      VARCHAR(100) NOT NULL,
    level       VARCHAR(20)  DEFAULT 'INFO',
    message     TEXT         NOT NULL,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- Orphan resources table (for cleanup)
CREATE TABLE IF NOT EXISTS orphan_resources (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL,
    resource_name VARCHAR(255) NOT NULL,
    host_ip     VARCHAR(50) DEFAULT NULL,
    slice_id    VARCHAR(64) DEFAULT NULL,
    details     TEXT DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

SELECT 'Database setup complete' AS status;
