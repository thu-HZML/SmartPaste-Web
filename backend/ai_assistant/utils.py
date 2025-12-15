# ai_assistant/utils.py
import os
import io
import chardet
import pypdf
import docx
from PIL import Image
import pytesseract

def parse_file_content(uploaded_file):
    """
    解析上传的文件流，返回文本内容。
    支持：PDF, Word, 图片(OCR), 各种代码/文本文件
    """
    text_content = ""
    filename = uploaded_file.name.lower()
    
    try:
        # 1. PDF 处理
        if filename.endswith('.pdf'):
            reader = pypdf.PdfReader(uploaded_file)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_content += extracted + "\n"

        # 2. Word 处理
        elif filename.endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                text_content += para.text + "\n"

        # 3. 图片处理 (OCR)
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
            try:
                # 注意：这需要服务器安装 tesseract-ocr 软件
                # Windows需配置路径，Linux需 apt install tesseract-ocr
                image = Image.open(uploaded_file)
                text_content = pytesseract.image_to_string(image, lang='chi_sim+eng')
                if not text_content.strip():
                    text_content = "[图片已读取，但未识别到清晰文字]"
            except Exception:
                text_content = "[服务器未安装OCR组件，无法提取图片文字，请直接提问]"

        # 4. 代码及纯文本文件 (.cpp, .py, .rs, .js, .txt, .md, .json 等)
        else:
            # 读取原始字节
            raw_data = uploaded_file.read()
            if not raw_data:
                return ""
                
            # 检测编码 (防止 GBK/UTF-8 乱码)
            result = chardet.detect(raw_data)
            encoding = result['encoding'] or 'utf-8'
            
            # 尝试解码
            try:
                text_content = raw_data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                # 降级重试
                text_content = raw_data.decode('utf-8', errors='ignore')

    except Exception as e:
        return f"[文件解析出错: {str(e)}]"

    return text_content