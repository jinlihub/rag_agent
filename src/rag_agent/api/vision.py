"""图片解析接口：上传图片 → 智谱视觉模型解析 → 返回 Markdown 内容。"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from rag_agent.api.deps import get_current_user
from rag_agent.config import get_settings
from rag_agent.clients.vision_client import parse_image

router = APIRouter(prefix="/api", tags=["vision"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_BYTES = 5 * 1024 * 1024  # 智谱视觉模型单图 5MB 上限


@router.post("/vision/parse")
async def parse_image_api(
    file: UploadFile, user: dict = Depends(get_current_user)
) -> dict:
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(422, "仅支持 jpg/png/webp/gif 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(422, "图片内容为空")
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "图片超过 5MB 上限，请压缩后再试")

    data_url = f"data:{file.content_type};base64,{base64.b64encode(data).decode()}"
    try:
        # zai SDK 为同步实现，放入线程池避免阻塞事件循环
        content = await run_in_threadpool(parse_image, data_url)
    except Exception as e:  # noqa: BLE001 —— 上游异常统一转为 502
        raise HTTPException(502, f"图片解析失败: {e}") from e
    return {"model": get_settings().vision_model, "content": content}
