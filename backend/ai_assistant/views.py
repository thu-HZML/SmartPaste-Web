# ai_assistant/views.py
import logging
import json
from django.conf import settings
from django.http import StreamingHttpResponse
from openai import OpenAI
from rest_framework import status, views, parsers
from rest_framework.response import Response
from rest_framework.request import Request
from .utils import parse_file_content

logger = logging.getLogger(__name__)

class ChatWithClipboardView(views.APIView):
    """
    POST: 处理剪贴板 AI 问答 (支持流式输出)
    请求体: multipart/form-data
    - type: text | image | file | none
    - content: 文本内容
    - file: 文件流
    - user_quest: 用户提问
    - provider: AI提供商
    - ai_config: AI模型配置
    - stream: boolean (默认 true) 是否开启流式输出
    """

    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request: Request) -> Response:
        """处理 AI 问答请求"""
        try:
            # 1. 解析基础参数
            msg_type = request.data.get("type", "none")
            content_text = request.data.get("content", "")
            user_quest = request.data.get("user_quest", "")
            file_path = request.data.get("file_path", "")
            uploaded_file = request.FILES.get("file")
            provider = request.data.get("provider", "default").lower()
            ai_config_str = request.data.get("ai_config")
            
            # 判断是否需要流式输出 (默认开启，除非显式设为 false)
            enable_stream = request.data.get("stream", "true").lower() == "true"

            # 解析 AI 配置
            ai_config = {}
            if ai_config_str:
                try:
                    ai_config = json.loads(ai_config_str)
                except json.JSONDecodeError:
                    logger.warning("Invalid ai_config JSON provided, using default settings.")

            # 2. 获取 Provider 配置 (URL, Key, Model)
            PROVIDER_BASE_URLS = {
                "openai": "https://api.openai.com/v1",
                "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "deepseek": "https://api.deepseek.com",
                "moonshot": "https://api.moonshot.cn/v1",
                "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            }

            api_key = settings.DEFAULT_API_KEY
            base_url = settings.DEFAULT_BASE_URL
            model_name = "DeepSeek-V3.2"
            temperature = 0.7

            # 配置逻辑处理 (与原代码保持一致)
            if provider == "default":
                if ai_config.get("temperature"): temperature = float(ai_config.get("temperature"))
                if ai_config.get("model"): model_name = ai_config.get("model")
            elif provider == "custom":
                base_url = ai_config.get("base_url")
                if not base_url:
                    return Response({"message": "Base URL is required for custom provider"}, status=400)
                api_key = ai_config.get("api_key")
                model_name = ai_config.get("model")
                if ai_config.get("temperature"): temperature = float(ai_config.get("temperature"))
            elif provider in PROVIDER_BASE_URLS:
                base_url = PROVIDER_BASE_URLS[provider]
                api_key = ai_config.get("api_key")
                model_name = ai_config.get("model")
                if ai_config.get("temperature"): temperature = float(ai_config.get("temperature"))
            else:
                return Response({"message": f"Unknown provider: {provider}"}, status=400)

            if not api_key or not model_name:
                return Response({"message": f"Missing API Key or Model for {provider}"}, status=400)

            # 3. 构建上下文数据
            context_data = ""
            if msg_type == "text":
                context_data = content_text
            elif msg_type in ["file", "image"]:
                if uploaded_file:
                    context_data = parse_file_content(uploaded_file)
                else:
                    context_data = f"[用户选中了文件: {file_path}，但上传失败或为空]"

            # 4. 构建 Messages
            system_instruction = "你是一个智能助手。请根据用户提供的【参考内容】（如果有）精准回答用户的【问题】。如果是代码，请分析逻辑并指出潜在问题。"
            
            if msg_type == "none" or not context_data.strip():
                messages = [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_quest},
                ]
            else:
                truncated_context = context_data[:30000]
                if len(context_data) > 30000:
                    truncated_context += "\n...(内容过长已截断)..."
                final_prompt = f"【参考内容】:\n{truncated_context}\n\n【用户问题】:\n{user_quest}"
                messages = [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": final_prompt},
                ]

            # 初始化客户端
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=30.0,
                max_retries=1,
            )

            # --- 分支 A: 如果不开启流式，走旧逻辑 ---
            if not enable_stream:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    stream=False,
                    temperature=temperature,
                )
                ai_reply = response.choices[0].message.content
                return Response({
                    "data": {
                        "reply": ai_reply,
                        "used_file": file_path if msg_type in ["file", "image"] else None,
                        "model_used": model_name,
                    }
                })

            # --- 分支 B: 开启流式输出 (StreamingHttpResponse) ---
            def event_stream():
                """生成器函数，用于逐步产生数据"""
                try:
                    stream_resp = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        stream=True, # 关键：开启流式
                        temperature=temperature,
                        stream_options={"include_usage": True} # 可选：请求Token使用量
                    )

                    for chunk in stream_resp:
                        # 处理内容增量
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            # 构造 SSE 格式数据: data: <json>\n\n
                            # 使用 JSON 封装以避免特殊字符导致前端解析错误
                            payload = json.dumps({"type": "delta", "content": content})
                            yield f"data: {payload}\n\n"

                    # 发送结束标记
                    yield "data: [DONE]\n\n"

                except Exception as stream_err:
                    logger.error(f"Stream Error: {stream_err}")
                    # 在流中发送错误信息给前端
                    error_payload = json.dumps({"type": "error", "message": str(stream_err)})
                    yield f"data: {error_payload}\n\n"

            # 返回流式响应
            return StreamingHttpResponse(
                event_stream(),
                content_type='text/event-stream'
            )

        except Exception as e:
            logger.error(f"AI Chat Error: {e}")
            return Response(
                {"message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )