CREATE DATABASE IF NOT EXISTS `healthcare_bot`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE `healthcare_bot`;

CREATE TABLE IF NOT EXISTS `users` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `username`        VARCHAR(50)     NOT NULL,
    `password_hash`   VARCHAR(255)    NOT NULL,
    `avatar_url`      VARCHAR(500)    NULL,
    `is_active`       TINYINT(1)      NOT NULL DEFAULT 1,
    `last_login_at`   DATETIME        NULL,
    `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `idx_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `conversations` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id`         BIGINT UNSIGNED NOT NULL,
    `title`           VARCHAR(200)    NOT NULL DEFAULT '新对话',
    `is_archived`     TINYINT(1)      NOT NULL DEFAULT 0,
    `message_count`   INT UNSIGNED    NOT NULL DEFAULT 0,
    `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_updated_at` (`updated_at`),
    CONSTRAINT `fk_conversations_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `messages` (
    `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `conversation_id`  BIGINT UNSIGNED NOT NULL,
    `role`             ENUM('user','assistant') NOT NULL,
    `content`          TEXT            NOT NULL,
    `tokens_used`      INT UNSIGNED    NULL,
    `audio_url`        VARCHAR(500)    NULL,
    `search_results`   JSON            NULL,
    `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_conversation_id` (`conversation_id`),
    INDEX `idx_created_at` (`created_at`),
    INDEX `idx_conv_role` (`conversation_id`, `role`),
    CONSTRAINT `fk_messages_conversation`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
