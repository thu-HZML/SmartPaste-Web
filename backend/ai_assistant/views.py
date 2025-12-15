# ai_assistant/views.py
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.conf import settings
from openai import OpenAI
from .utils import parse_file_content

logger = logging.getLogger(__name__)

# 初始化 DeepSeek 客户端
client = OpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=60.0,  # 将超时限制延长到 60 秒（默认通常是 5-10秒）
    
    max_retries=1  # 失败重试次数
)
@csrf_exempt
@require_POST
#@login_required
def chat_with_clipboard(request):
    """
    处理剪贴板 AI 问答
    请求体: multipart/form-data
    - type: text | image | file | none
    - content: 文本内容 (type=text时)
    - file: 文件流 (type=file/image时)
    - file_path: 原始路径 (可选)
    - user_quest: 用户提问
    """
    try:
        # 1. 解析参数
        msg_type = request.POST.get('type', 'none')
        content_text = request.POST.get('content', '')
        user_quest = request.POST.get('user_quest', '')
        file_path = request.POST.get('file_path', '') # 可用于日志记录
        uploaded_file = request.FILES.get('file')

        context_data = ""

        # 2. 根据类型提取上下文
        if msg_type == 'text':
            context_data = content_text
            
        elif msg_type in ['file', 'image']:
            if uploaded_file:
                # 调用 utils.py 中的解析函数
                context_data = parse_file_content(uploaded_file)
            else:
                # 只有路径没有文件流的情况 (理论上前端应拦截，这里做容错)
                context_data = f"[用户选中了文件: {file_path}，但上传失败或为空]"

        # 3. 构建 Prompt
        # 如果有上下文，拼接上下文；如果没有(type=none)，直接问。
        system_instruction = "你是一个智能助手。请根据用户提供的【参考内容】（如果有）精准回答用户的【问题】。如果是代码，请分析逻辑并指出潜在问题。"
        
        if msg_type == 'none' or not context_data.strip():
            # 直接提问模式
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_quest}
            ]
        else:
            # 截断过长的上下文，防止 Token 溢出 (DeepSeek V3 支持很长，但建议设个安全阈值，如 30000 字符)
            truncated_context = context_data[:30000]
            if len(context_data) > 30000:
                truncated_context += "\n...(内容过长已截断)..."

            final_prompt = f"【参考内容】:\n{truncated_context}\n\n【用户问题】:\n{user_quest}"
            
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": final_prompt}
            ]

        # 4. 调用 DeepSeek API
        response = client.chat.completions.create(
            
            model="DeepSeek-V3.2", 
            messages=messages,
            stream=False,
            temperature=0.7
        )

        ai_reply = response.choices[0].message.content

        return JsonResponse({
            'code': 200,
            'status': 'success',
            'data': {
                'reply': ai_reply,
                'used_file': file_path if msg_type in ['file', 'image'] else None
            }
        })

    except Exception as e:
        logger.error(f"AI Chat Error: {e}")
        return JsonResponse({
            'code': 500,
            'status': 'error',
            'message': str(e)
        }, status=500)