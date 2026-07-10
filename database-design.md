# 数据库设计文档

## 概述

为 Q-A-Bot for Healthcare Sector 项目引入 MySQL 关系型数据库，用于实现用户注册登录和对话历史持久化。

### 当前状态
- 项目无用户认证系统，无对话历史存储
- 所有会话状态仅存在于 WebSocket 连接的短生命周期内
- LLM 调用无对话上下文，每轮问答相互独立

### 新增能力
- 用户注册与登录（JWT 认证）
- 多轮对话上下文传递（LLM 携带历史消息）
- 对话历史浏览、搜索和恢复

---

## 系统架构变更

```
 前端 (Vue 3 SPA)
      │  HTTP (REST)         │  WebSocket
      ▼                      ▼
 ┌─────────────┐    ┌────────────────┐
 │ Auth API    │    │ /ws (WebSocket)│
 │ /login      │    │ 原有 LLM + ASR │
 │ /register   │    │ + TTS pipeline │
 │ /refresh    │    │ + 对话存储逻辑 │
 └──────┬──────┘    └───────┬────────┘
        │                   │
        ▼                   ▼
 ┌─────────────────────────────────────┐
 │           MySQL Database            │
 │  users | conversations | messages   │
 └─────────────────────────────────────┘
```

- 认证接口使用 HTTP REST，在 WebSocket 连接建立前验证 JWT
- WebSocket 连接时由前端在 query string 或首个消息中传递 JWT token
- 对话消息在 pipeline 执行完毕后异步写入 MySQL

---

## 数据库表设计

### ER 图关系

```
┌──────────┐       ┌─────────────────┐       ┌──────────────┐
│  users   │──1:N──│  conversations  │──1:N──│   messages   │
└──────────┘       └─────────────────┘       └──────────────┘
    │                                              │
    │                                              │ (JSON 内嵌)
    │                                              ▼
    │                                       RAG 检索结果
    │                                       (search_results 字段)
```

---

## 表详细定义

### 1. `users` — 用户表

存储注册用户的基本信息和认证凭据。密码使用 bcrypt 哈希存储，禁止明文。

| 字段名            | 数据类型                       | 约束                            | 说明                 |
| ----------------- | ------------------------------ | ------------------------------- | -------------------- |
| `id`              | `BIGINT UNSIGNED`              | `PRIMARY KEY AUTO_INCREMENT`    | 用户唯一标识         |
| `username`        | `VARCHAR(50)`                  | `NOT NULL UNIQUE`               | 用户名，登录用       |
| `password_hash`   | `VARCHAR(255)`                 | `NOT NULL`                      | bcrypt 哈希后的密码  |
| `avatar_url`      | `VARCHAR(500)`                 | `NULL`                          | 头像 URL（预留）     |
| `is_active`       | `TINYINT(1)`                   | `NOT NULL DEFAULT 1`            | 账号是否启用         |
| `last_login_at`   | `DATETIME`                     | `NULL`                          | 上次登录时间         |
| `created_at`      | `DATETIME`                     | `NOT NULL DEFAULT CURRENT_TIMESTAMP` | 注册时间         |
| `updated_at`      | `DATETIME`                     | `NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | 更新时间 |

**索引：**
```sql
UNIQUE INDEX idx_username (username);
```

**DDL：**
```sql
CREATE TABLE `users` (
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
```

---

### 2. `conversations` — 对话会话表

每一条记录代表用户发起的一次完整对话会话。一个用户可以拥有多条对话。

| 字段名            | 数据类型                       | 约束                            | 说明                   |
| ----------------- | ------------------------------ | ------------------------------- | ---------------------- |
| `id`              | `BIGINT UNSIGNED`              | `PRIMARY KEY AUTO_INCREMENT`    | 对话唯一标识           |
| `user_id`         | `BIGINT UNSIGNED`              | `NOT NULL`                      | 所属用户 ID            |
| `title`           | `VARCHAR(200)`                 | `NOT NULL DEFAULT '新对话'`     | 对话标题               |
| `is_archived`     | `TINYINT(1)`                   | `NOT NULL DEFAULT 0`            | 是否归档               |
| `message_count`   | `INT UNSIGNED`                 | `NOT NULL DEFAULT 0`            | 消息总数（冗余字段）   |
| `created_at`      | `DATETIME`                     | `NOT NULL DEFAULT CURRENT_TIMESTAMP` | 创建时间           |
| `updated_at`      | `DATETIME`                     | `NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | 最新活动时间 |

**索引：**
```sql
INDEX idx_user_id (user_id);
INDEX idx_updated_at (updated_at);
```

**外键：**
```sql
CONSTRAINT fk_conversations_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE;
```

> `ON DELETE CASCADE`：用户删除时级联删除其所有对话。

**DDL：**
```sql
CREATE TABLE `conversations` (
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
```

---

### 3. `messages` — 消息表

存储对话中的每一条消息（用户提问 + 助手回答）。RAG 检索结果直接以 JSON 格式内嵌于消息中，无需独立建表。

| 字段名             | 数据类型                       | 约束                            | 说明                          |
| ------------------ | ------------------------------ | ------------------------------- | ----------------------------- |
| `id`               | `BIGINT UNSIGNED`              | `PRIMARY KEY AUTO_INCREMENT`    | 消息唯一标识                  |
| `conversation_id`  | `BIGINT UNSIGNED`              | `NOT NULL`                      | 所属对话 ID                   |
| `role`             | `ENUM('user','assistant')`     | `NOT NULL`                      | 消息角色                      |
| `content`          | `TEXT`                         | `NOT NULL`                      | 消息正文                      |
| `tokens_used`      | `INT UNSIGNED`                 | `NULL`                          | LLM 消耗 token 数（助手消息） |
| `audio_url`        | `VARCHAR(500)`                 | `NULL`                          | TTS 生成音频存储路径（预留）  |
| `search_results`   | `JSON`                         | `NULL`                          | RAG 检索结果（JSON 数组）     |
| `created_at`       | `DATETIME`                     | `NOT NULL DEFAULT CURRENT_TIMESTAMP` | 消息时间                  |

> `search_results` JSON 结构示例：
> ```json
> [
>   {
>     "doc_id": "chunk_0012",
>     "score": 0.87,
>     "question": "高血压患者饮食应注意什么？",
>     "answer": "高血压患者应低盐低脂饮食..."
>   }
> ]
> ```

**索引：**
```sql
INDEX idx_conversation_id (conversation_id);
INDEX idx_created_at (created_at);
INDEX idx_conv_role (conversation_id, role);  -- 联合索引，加速查询
```

**外键：**
```sql
CONSTRAINT fk_messages_conversation
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    ON DELETE CASCADE ON UPDATE CASCADE;
```

> `ON DELETE CASCADE`：对话删除时级联删除其所有消息。

**DDL：**
```sql
CREATE TABLE `messages` (
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
```

---

## 完整建库脚本

```sql
-- ============================================================
-- Q-A Bot for Healthcare Sector — 数据库初始化脚本
-- MySQL 8.0+
-- ============================================================

CREATE DATABASE IF NOT EXISTS `healthcare_bot`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE `healthcare_bot`;

-- 用户表
CREATE TABLE `users` (
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

-- 对话会话表
CREATE TABLE `conversations` (
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

-- 消息表
CREATE TABLE `messages` (
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
```

---

## JWT 认证流程

### Token 结构

| 字段   | 说明                     |
| ------ | ------------------------ |
| `sub`  | 用户 ID（`user.id`）     |
| `exp`  | 过期时间，建议 7 天      |
| `iat`  | 签发时间                 |
| `type` | `access` 或 `refresh`    |

- **Access Token**：有效期 30 分钟，用于 API 鉴权
- **Refresh Token**：有效期 7 天，用于刷新 Access Token（存储在 `users` 表或 Redis 中）

### 注册流程（HTTP REST）

```
POST /api/auth/register
Body: { "username": "...", "password": "..." }

1. 参数校验（用户名长度 3-50，密码长度 ≥ 8）
2. 检查 username 是否已存在
3. password 使用 bcrypt 哈希 → password_hash
4. INSERT INTO users → 返回 user_id
5. 签发 access_token + refresh_token
6. 返回 { access_token, refresh_token, user: { id, username } }
```

### 登录流程（HTTP REST）

```
POST /api/auth/login
Body: { "username": "...", "password": "..." }

1. 通过 username 查询用户
2. 使用 bcrypt.verify(password, password_hash) 校验
3. 校验通过 → 更新 last_login_at
4. 签发 access_token + refresh_token
5. 返回 { access_token, refresh_token, user: { id, username } }
```

### WebSocket 鉴权

```
WebSocket 连接时前端传 token 参数：
  ws://host/ws?mode=w2&token=<access_token>

服务端在 on_connect 中：
1. 从 query params 中提取 token
2. 验证 JWT 签名和有效期
3. 解析 user_id → 注入 WebSocket 会话上下文
4. 后续消息处理均可获取当前用户身份
```

---

## 对话历史读写流程

### 新建对话

```
用户首次发送消息时：
1. INSERT INTO conversations (user_id)
   → 返回 conversation_id
2. 用第一条用户消息的前 30 个字符自动生成 title
   → UPDATE conversations SET title = ? WHERE id = ?
3. 通知前端 conversation_id
```

### 写入消息

```
每轮问答完成后（pipeline done 时）：
1. INSERT INTO messages (conversation_id, role='user', content=asr_final)
2. INSERT INTO messages (conversation_id, role='assistant', content=answer,
                         tokens_used=..., search_results=...)
3. UPDATE conversations SET message_count = message_count + 2, updated_at = NOW()
```

### 加载历史上下文

```
每轮新的用户提问到达时：
1. 根据 conversation_id 查询近 N 条消息：
   SELECT role, content FROM messages
   WHERE conversation_id = ? AND role IN ('user','assistant')
   ORDER BY created_at ASC LIMIT ?;

2. 格式化为 LLM messages 数组：
   [
     {"role": "system", "content": "你是医疗咨询助手..."},
     {"role": "user", "content": "之前的问题1"},
     {"role": "assistant", "content": "之前的回答1"},
     {"role": "user", "content": "当前问题"}
   ]

3. 控制上下文窗口：
   - 默认携带最近 10 轮对话（20 条消息）或 token 总量 < 4K
   - 超出时裁剪最早的消息
```

### 查询对话列表

```
GET /api/conversations?archived=0&page=1&size=20

SELECT id, title, message_count, created_at, updated_at
FROM conversations
WHERE user_id = ? AND is_archived = ?
ORDER BY updated_at DESC
LIMIT ? OFFSET ?;
```

### 查询对话详情

```
GET /api/conversations/{id}/messages

SELECT id, role, content, tokens_used, search_results, created_at
FROM messages
WHERE conversation_id = ?
ORDER BY created_at ASC;
```

---

## 新依赖项

需要在 `requirements.txt` 中新增：

```
# 数据库
sqlalchemy[asyncio]>=2.0        # 异步 ORM
aiomysql>=0.2.0                 # MySQL 异步驱动
pymysql>=1.1.0                  # MySQL 同步驱动（用于 Alembic）

# 认证
python-jose[cryptography]>=3.3  # JWT 编解码
bcrypt>=4.0                     # 密码哈希
python-multipart>=0.0.6         # 表单解析（login/register）

# 数据库迁移
alembic>=1.13                   # 数据库迁移管理
```

需要新增环境变量（`.env`）：

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=healthcare_bot
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=healthcare_bot
MYSQL_POOL_SIZE=10
MYSQL_POOL_RECYCLE=3600

# JWT
JWT_SECRET_KEY=your-secret-key-at-least-32-chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## 推荐的后端代码结构

```
backend/
├── database/
│   ├── __init__.py          # 数据库引擎和会话工厂
│   ├── models.py            # SQLAlchemy ORM 模型
│   └── migrations/          # Alembic 迁移文件
│
├── api/
│   ├── __init__.py
│   ├── auth.py              # POST /register, /login, /refresh
│   ├── conversations.py     # GET/POST/DELETE 对话 CRUD
│   └── dependencies.py      # 依赖注入：get_db, get_current_user
│
├── auth/
│   ├── __init__.py
│   ├── jwt.py               # JWT 签发与验证
│   └── security.py          # bcrypt 密码哈希
│
└── main.py                  # 注册路由、启动数据库连接池
```

---

## 性能考量与扩展预留

| 考量点               | 当前方案                                 | 扩展建议                             |
| -------------------- | ---------------------------------------- | ------------------------------------ |
| **消息量增长**       | 单表存储，按 conversation_id 索引查询    | 消息量 > 千万级时可按月分表或归档    |
| **历史上下文窗口**   | 应用层限制最近 N 轮                       | 可结合 ChromaDB 做长短期记忆混合检索 |
| **RAG 检索结果**     | JSON 内嵌在 messages 表                   | 可独立建 `rag_logs` 表做检索分析     |
| **并发 WebSocket**   | 每条连接一个 MySQL 连接                  | 使用连接池（默认 10+）控制           |
| **Token 黑名单**     | 无状态 JWT（信任过期时间）                | 需要时可引入 Redis 做 token 吊销列表 |
| **音频存储**         | `audio_url` 预留字段，暂不存储            | 可接入 OSS/S3 存储 TTS 输出          |

---

## 注意事项

1. **密码安全**：密码使用 bcrypt（cost factor ≥ 12）哈希，不存储明文，不记录到日志。
2. **SQL 注入防护**：使用 SQLAlchemy ORM 参数化查询，禁止字符串拼接 SQL。
3. **JWT 密钥管理**：`JWT_SECRET_KEY` 从环境变量读取，不可硬编码，不可提交到 Git。
4. **字符集**：全库使用 `utf8mb4`，支持 emoji 和生僻字。
5. **事务**：写消息时使用事务保证 user 消息和 assistant 消息写入的原子性。
6. **`message_count` 冗余字段**：每次写入消息时同步更新，避免高频 COUNT 查询。
