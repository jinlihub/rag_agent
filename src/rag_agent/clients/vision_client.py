"""图片内容解析客户端：智谱视觉模型 glm-4.6v-flashx（zai SDK / ZhipuAiClient）。

输入用户上传图片的 data URL（base64），输出 Markdown 文本：
文字逐段转录、表格还原为 Markdown 表格、结构图用层级列表描述。
"""

from __future__ import annotations

from rag_agent.config import get_settings

_PARSE_PROMPT = (
    "请解析这张图片的内容，用 Markdown 输出：\n"
    "1. 图中的文字逐段完整转录，保持原有层级与编号；\n"
    "2. 表格还原为 Markdown 表格；\n"
    "3. 流程图/组织结构图用层级列表描述；\n"
    "4. 只描述图片中实际存在的内容，不要推测或补充图中没有的信息。"
)


def parse_image(data_url: str) -> str:
    """调用视觉模型解析图片，返回 Markdown 文本（可能为空串，由调用方兜底）。"""
    from zai import ZhipuAiClient

    s = get_settings()
    client = ZhipuAiClient(api_key=s.llm_api_key, timeout=60)
    resp = client.chat.completions.create(
        model=s.vision_model,  # glm-4.6v-flashx
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _PARSE_PROMPT},
                ],
            }
        ],
        temperature=0.1,
    )
    return (resp.choices[0].message.content or "").strip()
