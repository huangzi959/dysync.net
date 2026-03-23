# dy.sync 外部接口（Python3）

这是一个轻量适配层：
- 对外提供你自己的接口（`/api/v1/videos`）
- 内部自动登录 dy.sync（`/api/Auth/Login`）并调用其分页接口（`/api/Video/paged`）

## 1. 安装依赖

```bash
cd integrations/python3_adapter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置环境变量

```bash
export DYSYNC_BASE_URL="http://127.0.0.1:10101"
export DYSYNC_USERNAME="douyin"
export DYSYNC_PASSWORD="douyin2026"
export REQUEST_TIMEOUT_SECONDS="20"
```

## 3. 启动

```bash
uvicorn app:app --host 0.0.0.0 --port 18080
```

## 4. 调用示例

### 健康检查
```bash
curl 'http://127.0.0.1:18080/health'
```

### 拉取视频分页
```bash
curl 'http://127.0.0.1:18080/api/v1/videos?page_index=1&page_size=20&title=旅行'
```

### 拉取轻量ID列表（便于增量同步）
```bash
curl 'http://127.0.0.1:18080/api/v1/video-ids?page_index=1&page_size=50'
```

### 获取可下载链接（JSON返回）
```bash
curl 'http://127.0.0.1:18080/api/v1/download/7462157589220000000?redirect=false'
```

### 直接下载（302跳转）
```bash
curl -L -o video.mp4 'http://127.0.0.1:18080/api/v1/download/7462157589220000000'
```

## 5. 返回说明

- `/api/v1/videos`：原样返回 dy.sync 的响应结构。
- `/api/v1/video-ids`：返回精简字段：`id`、`awemeId`、`syncTime`、`playUrl`。
- `/api/v1/download/{video_id}`：返回下载链接或直接 302 跳转到下载流。

## 6. 对接建议

- 生产环境建议把 `DYSYNC_USERNAME`/`DYSYNC_PASSWORD` 放入密钥管理系统，不要明文写死。
- 如需稳定增量同步，可基于 `syncTime` 或 `awemeId` 做游标。
