-- 创建系统设置表（不包括数据库配置）
CREATE TABLE IF NOT EXISTS system_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    setting_type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_setting_key (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认爬虫配置（不包括数据库配置）
INSERT INTO system_settings (setting_key, setting_value, setting_type, description) VALUES
('out_dir', './output', 'string', '输出目录'),
('torrent_download_dir', './torrents', 'string', '种子下载目录'),
('delay', '0.5', 'float', '请求延迟时间(秒)'),
('test_mode', 'true', 'boolean', '测试模式'),
('test_limit', '5', 'integer', '测试模式限制数量'),
('allow_v2', 'false', 'boolean', '允许v2版本种子'),
('sites', '[]', 'json', '站点配置列表');