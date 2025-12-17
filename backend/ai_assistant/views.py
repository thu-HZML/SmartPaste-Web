# ai_assistant/views.py
import logging
import json
from django.conf import settings
from openai import OpenAI
from rest_framework import status, views, parsers
from rest_framework.response import Response
from rest_framework.request import Request
from .utils import parse_file_content

logger = logging.getLogger(__name__)


class ChatWithClipboardView(views.APIView):
    """
    POST: 处理剪贴板 AI 问答
    请求体: multipart/form-data
    - type: text | image | file | none
    - content: 文本内容 (type=text时)
    - file: 文件流 (type=file/image时)
    - file_path: 原始路径 (可选)
    - user_quest: 用户提问
    - provider: AI提供商 (default | openai | google | custom | ...)
    - ai_config: AI模型配置 (JSON字符串, 可选)
        - api_key: API密钥 (custom或公开厂商时)
        - base_url: 基础URL (custom时)
        - model: 模型名称
        - temperature: 采样温度
    """

    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request: Request) -> Response:
        """处理 AI 问答请求"""
        try:
            # 1. 解析参数
            msg_type = request.data.get("type", "none")
            content_text = request.data.get("content", "")
            user_quest = request.data.get("user_quest", "")
            file_path = request.data.get("file_path", "")  # 可用于日志记录
            uploaded_file = request.FILES.get("file")
            provider = request.data.get("provider", "default").lower()
            ai_config_str = request.data.get("ai_config")

            # 解析 AI 配置
            ai_config = {}
            if ai_config_str:
                try:
                    ai_config = json.loads(ai_config_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid ai_config JSON provided, using default settings."
                    )

            # 预设的公开厂商 Base URL
            PROVIDER_BASE_URLS = {
                "openai": "https://api.openai.com/v1",
                "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "deepseek": "https://api.deepseek.com",
                "moonshot": "https://api.moonshot.cn/v1",
                "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            }

            # 获取配置参数

            # 默认值
            api_key = settings.DEFAULT_API_KEY
            base_url = settings.DEFAULT_BASE_URL
            model_name = "DeepSeek-V3.2"
            temperature = 0.7

            if provider == "default":
                # 使用默认配置，但允许覆盖部分参数
                if ai_config.get("temperature"):
                    temperature = float(ai_config.get("temperature"))
                if ai_config.get("model"):
                    model_name = ai_config.get("model")

            elif provider == "custom":
                # 自定义提供商，必须提供 base_url
                base_url = ai_config.get("base_url")
                if not base_url:
                    return Response(
                        {
                            "message": "Base URL is required for custom provider",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                api_key = ai_config.get("api_key")
                model_name = ai_config.get("model")
                if ai_config.get("temperature"):
                    temperature = float(ai_config.get("temperature"))

            elif provider in PROVIDER_BASE_URLS:
                # 公开厂商
                base_url = PROVIDER_BASE_URLS[provider]
                api_key = ai_config.get("api_key")
                model_name = ai_config.get("model")
                if ai_config.get("temperature"):
                    temperature = float(ai_config.get("temperature"))

            else:
                # 未知提供商，尝试作为 custom 处理，或者报错
                # 这里选择报错以明确意图
                return Response(
                    {
                        "message": f"Unknown provider: {provider}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 最终校验
            if not api_key:
                return Response(
                    {
                        "message": f"API Key is required for provider {provider}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not model_name:
                return Response(
                    {
                        "message": f"Model name is required for provider {provider}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 初始化 OpenAI 客户端
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=30.0,  # 超时限制 30 秒
                max_retries=1,  # 失败重试次数
            )

            context_data = ""

            # 2. 根据类型提取上下文
            if msg_type == "text":
                context_data = content_text

            elif msg_type in ["file", "image"]:
                if uploaded_file:
                    # 调用 utils.py 中的解析函数
                    context_data = parse_file_content(uploaded_file)
                else:
                    # 只有路径没有文件流的情况 (理论上前端应拦截，这里做容错)
                    context_data = f"[用户选中了文件: {file_path}，但上传失败或为空]"

            # 3. 构建 Prompt
            # 如果有上下文，拼接上下文；如果没有(type=none)，直接问。
            system_instruction = "你是一个智能助手。请根据用户提供的【参考内容】（如果有）精准回答用户的【问题】。如果是代码，请分析逻辑并指出潜在问题。"

            if msg_type == "none" or not context_data.strip():
                # 直接提问模式
                messages = [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_quest},
                ]
            else:
                # 截断过长的上下文，防止 Token 溢出 (DeepSeek V3 支持很长，但建议设个安全阈值，如 30000 字符)
                truncated_context = context_data[:30000]
                if len(context_data) > 30000:
                    truncated_context += "\n...(内容过长已截断)..."

                final_prompt = (
                    f"【参考内容】:\n{truncated_context}\n\n【用户问题】:\n{user_quest}"
                )

                messages = [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": final_prompt},
                ]

            # 4. 调用 DeepSeek API
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=False,
                temperature=temperature,
            )

            ai_reply = response.choices[0].message.content

            return Response(
                {
                    "data": {
                        "reply": ai_reply,
                        "used_file": file_path
                        if msg_type in ["file", "image"]
                        else None,
                        "model_used": model_name,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"AI Chat Error: {e}")
            return Response(
                {"message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
