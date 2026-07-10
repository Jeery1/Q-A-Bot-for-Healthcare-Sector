# 接口文档

## 通用说明

- **基础地址**: `https://project-of-sun.xin`
- **认证方式**: 除注册/登录外，HTTP 请求需在 Header 携带 `Authorization: Bearer <access_token>`
- **限流**: 超出限制返回 429，响应体 `{"detail":"请求过于频繁，请等待 X 秒后重试"}`
- **WebSocket**: HTTPS 页面使用 `wss://`，HTTP 页面使用 `ws://`

---

## 1. 认证接口

### 1.1 注册

```
POST /api/auth/register
```

**限流**: 3 次/分钟

**请求体**:

```json
{
  "username": "string (3-50字符)",
  "password": "string (6-128字符)"
}
```

**成功响应** (200):

```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "user": { "id": 1, "username": "zhangsan" }
}
```

**错误响应**:

| 状态码 | detail |
|--------|--------|
| 409 | 用户名已存在 |
| 429 | 请求过于频繁，请等待 60 秒后重试 |

---

### 1.2 登录

```
POST /api/auth/login
```

**限流**: 5 次/分钟

**请求体**:

```json
{
  "username": "string",
  "password": "string"
}
```

**成功响应** (200):

```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "user": { "id": 1, "username": "zhangsan" }
}
```

**错误响应**:

| 状态码 | detail |
|--------|--------|
| 401 | 用户名或密码错误 |
| 429 | 请求过于频繁，请等待 60 秒后重试 |

---

### 1.3 刷新令牌

```
POST /api/auth/refresh
```

**限流**: 10 次/分钟

**请求体**:

```json
{
  "refresh_token": "string"
}
```

**成功响应** (200):

```json
{
  "access_token": "eyJhbG... (新 Access Token)",
  "refresh_token": "eyJhbG... (新 Refresh Token)",
  "user": { "id": 1, "username": "zhangsan" }
}
```

**错误响应**:

| 状态码 | detail |
|--------|--------|
| 401 | 刷新令牌无效或已过期 |
| 401 | 无效的令牌类型 |
| 401 | 用户不存在 |
| 429 | 请求过于频繁，请等待 60 秒后重试 |

---

## 2. 对话接口

所有接口需要 Header: `Authorization: Bearer <access_token>`

### 2.1 获取对话列表

```
GET /api/conversations?archived=0&page=1&size=20
```

**限流**: 30 次/分钟

**查询参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| archived | bool | false | 是否获取已归档对话 |
| page | int (>=1) | 1 | 页码 |
| size | int (1-100) | 20 | 每页条数 |

**成功响应** (200):

```json
[
  {
    "id": 1,
    "title": "感冒了吃什么药",
    "is_archived": false,
    "message_count": 4,
    "created_at": "2026-07-10T10:00:00",
    "updated_at": "2026-07-10T10:05:00"
  }
]
```

---

### 2.2 创建对话

```
POST /api/conversations
```

**限流**: 10 次/分钟

**请求体**: 无

**成功响应** (200):

```json
{
  "id": 2,
  "title": "新对话",
  "is_archived": false,
  "message_count": 0,
  "created_at": "2026-07-10T12:00:00",
  "updated_at": "2026-07-10T12:00:00"
}
```

---

### 2.3 获取对话消息

```
GET /api/conversations/{conv_id}/messages
```

**限流**: 30 次/分钟

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| conv_id | int | 对话 ID |

**成功响应** (200):

```json
[
  {
    "id": 1,
    "role": "user",
    "content": "感冒了吃什么药",
    "tokens_used": null,
    "search_results": null,
    "created_at": "2026-07-10T10:00:00"
  },
  {
    "id": 2,
    "role": "assistant",
    "content": "感冒时可根据症状选择...",
    "tokens_used": 156,
    "search_results": [
      {
        "id": "huatuo_001",
        "question": "感冒吃什么药好得快",
        "answer": "普通感冒以对症治疗为主...",
        "score": 0.89
      }
    ],
    "created_at": "2026-07-10T10:00:05"
  }
]
```

**字段说明**:

| 字段 | 说明 |
|------|------|
| role | `user` 用户消息 / `assistant` AI 回答 |
| tokens_used | LLM 消耗 token 数，仅 assistant 消息有值 |
| search_results | RAG 检索到的知识库参考文档，按匹配度降序排列 |

**错误响应**:

| 状态码 | detail |
|--------|--------|
| 404 | 对话不存在 |

---

### 2.4 删除对话

```
DELETE /api/conversations/{conv_id}
```

**限流**: 10 次/分钟

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| conv_id | int | 对话 ID |

**成功响应** (200):

```json
{ "ok": true }
```

**错误响应**:

| 状态码 | detail |
|--------|--------|
| 404 | 对话不存在 |

---

## 3. WebSocket 接口

### 3.1 实时对话

```
wss://project-of-sun.xin/ws?mode=w2&token=<access_token>&conv_id=<conversation_id>
```

**查询参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| mode | string | w1 | `w1` 非流式 / `w2` 全流式（推荐）/ `w3` 安全流式 |
| token | string | - | Access Token |
| conv_id | int | 0 | 对话 ID，0 表示新对话 |

**客户端 → 服务端 (发送)**:

##### 文本输入

```json
{ "type": "text_query", "text": "感冒了怎么办" }
```

##### 语音输入

```
二进制 PCM Int16 音频数据 (16kHz 单声道)
```

##### 语音结束

```json
{ "type": "audio_end" }
```

**服务端 → 客户端 (接收)**:

| 消息类型 | 说明 | 格式 |
|----------|------|------|
| `asr_partial` | 语音识别中间结果 | `{"type":"asr_partial","text":"..."}` |
| `asr_final` | 语音识别最终结果 | `{"type":"asr_final","text":"..."}` |
| `llm_token` | LLM 流式 token | `{"type":"llm_token","text":"..."}` |
| `answer` | 完整回答（非流式模式） | `{"type":"answer","text":"..."}` |
| `rag_info` | RAG 检索参考来源 | `{"type":"rag_info","docs":[...]}` |
| `tts_chunk` | TTS 音频片段 | `{"type":"tts_chunk","data":"base64..."}` |
| `audio` | 完整音频（非流式模式） | `{"type":"audio","data":"base64..."}` |
| `conv_created` | 新对话已创建 | `{"type":"conv_created","conv_id":1,"title":"..."}` |
| `done` | 本轮处理完成 | `{"type":"done","timings":{"asr":0.5,"llm":3.2,"total":5.1}}` |
| `error` | 错误 | `{"type":"error","text":"..."}` |

**认证失败时**: 服务端发送 `{"error": "认证失败，请重新登录"}` 后关闭连接。

---

## 4. Token 说明

| Token | 有效期 | 用途 |
|-------|--------|------|
| Access Token | 30 分钟 | API 认证、WebSocket 连接 |
| Refresh Token | 7 天 | 刷新 Access Token |

- Access Token 过期前 1 分钟前端自动静默续期
- 续期失败（Refresh Token 也过期）自动跳转登录页

## 5. 通用错误响应

| 状态码 | 说明 |
|--------|------|
| 401 | 未认证或令牌无效 |
| 404 | 资源不存在 |
| 409 | 资源冲突（如用户名已存在） |
| 422 | 请求参数校验失败 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |
