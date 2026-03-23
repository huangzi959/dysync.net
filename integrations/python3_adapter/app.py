import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import RedirectResponse


DYSYNC_BASE_URL = os.getenv("DYSYNC_BASE_URL", "http://127.0.0.1:10101")
DYSYNC_USERNAME = os.getenv("DYSYNC_USERNAME", "douyin")
DYSYNC_PASSWORD = os.getenv("DYSYNC_PASSWORD", "douyin2026")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))


class TokenCache:
    def __init__(self) -> None:
        self.token: Optional[str] = None
        self.expires_at: float = 0

    def valid(self) -> bool:
        # 提前 60 秒刷新 token，避免临界过期
        return bool(self.token) and time.time() < self.expires_at - 60


class VideoQuery(BaseModel):
    page_index: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    title: Optional[str] = None
    author: Optional[str] = None
    viedo_type: Optional[str] = None
    tag: Optional[str] = None
    cookie_id: Optional[str] = None
    sort_field: Optional[str] = None
    sort_order: Optional[str] = None


class DysyncClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token_cache = TokenCache()

    async def _login(self) -> str:
        login_url = f"{self.base_url}/api/Auth/Login"
        payload = {"userName": self.username, "password": self.password}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(login_url, json=payload)

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"登录 dy.sync 失败: HTTP {response.status_code}")

        data = response.json()
        token = data.get("token")
        expires_ms = data.get("expires", 24 * 60 * 60 * 1000)
        if not token:
            raise HTTPException(status_code=502, detail=f"登录 dy.sync 成功但未返回 token: {data}")

        self._token_cache.token = token
        self._token_cache.expires_at = time.time() + expires_ms / 1000
        return token

    async def _get_token(self) -> str:
        if self._token_cache.valid():
            return self._token_cache.token or ""
        return await self._login()

    async def get_videos(self, query: VideoQuery) -> Dict[str, Any]:
        token = await self._get_token()
        url = f"{self.base_url}/api/Video/paged"
        payload = {
            "pageIndex": query.page_index,
            "pageSize": query.page_size,
            "title": query.title,
            "author": query.author,
            "viedoType": query.viedo_type,
            "tag": query.tag,
            "cookieId": query.cookie_id,
            "sortField": query.sort_field,
            "sortOrder": query.sort_order,
        }

        # 去掉空值，避免触发不必要的后端逻辑
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )

        if response.status_code == 401:
            token = await self._login()
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"查询视频失败: HTTP {response.status_code}, body={response.text}")

        return response.json()

    def build_play_url(self, video_id: str) -> str:
        return f"{self.base_url}/api/Video/play/{video_id}"


app = FastAPI(title="dy.sync Python3 Adapter", version="1.0.0")
client = DysyncClient(
    base_url=DYSYNC_BASE_URL,
    username=DYSYNC_USERNAME,
    password=DYSYNC_PASSWORD,
)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/videos")
async def list_videos(
    page_index: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    title: Optional[str] = None,
    author: Optional[str] = None,
    viedo_type: Optional[str] = None,
    tag: Optional[str] = None,
    cookie_id: Optional[str] = None,
    sort_field: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> Dict[str, Any]:
    """
    外部系统调用本接口即可拿到 dy.sync 视频分页数据。
    """
    query = VideoQuery(
        page_index=page_index,
        page_size=page_size,
        title=title,
        author=author,
        viedo_type=viedo_type,
        tag=tag,
        cookie_id=cookie_id,
        sort_field=sort_field,
        sort_order=sort_order,
    )
    return await client.get_videos(query)


@app.get("/api/v1/video-ids")
async def list_video_ids(
    page_index: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    cookie_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    示例：返回轻量字段，方便外部增量同步。
    """
    result = await client.get_videos(
        VideoQuery(page_index=page_index, page_size=page_size, cookie_id=cookie_id)
    )

    data: List[Dict[str, Any]] = result.get("data", {}).get("data", []) if isinstance(result.get("data"), dict) else []
    items = [
        {
            "id": x.get("id"),
            "awemeId": x.get("awemeId"),
            "syncTime": x.get("syncTime"),
            "playUrl": client.build_play_url(x.get("id")) if x.get("id") else None,
        }
        for x in data
    ]

    return {
        "total": result.get("data", {}).get("total", 0) if isinstance(result.get("data"), dict) else 0,
        "items": items,
    }


@app.get("/api/v1/download/{video_id}")
async def download_video(video_id: str, redirect: bool = Query(True)) -> Any:
    """
    对外提供“下载地址”接口：
    - redirect=true: 302 跳转到 dy.sync 播放/下载流地址（默认）
    - redirect=false: 返回可下载的源链接
    """
    play_url = client.build_play_url(video_id)
    if redirect:
        return RedirectResponse(url=play_url, status_code=302)
    return {"videoId": video_id, "downloadUrl": play_url}
