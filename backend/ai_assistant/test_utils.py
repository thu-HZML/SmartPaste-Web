import unittest
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from ai_assistant.utils import parse_file_content


class AIUtilsTests(SimpleTestCase):
    @patch("ai_assistant.utils.pypdf.PdfReader")
    def test_parse_pdf(self, mock_pdf_reader):
        """Test parsing PDF files"""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF Content"
        mock_pdf_reader.return_value.pages = [mock_page]

        mock_file = MagicMock()
        mock_file.name = "test.pdf"

        content = parse_file_content(mock_file)
        self.assertIn("PDF Content", content)

    @patch("ai_assistant.utils.docx.Document")
    def test_parse_docx(self, mock_docx):
        """Test parsing DOCX files"""
        mock_doc = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "Docx Content"
        mock_doc.paragraphs = [mock_para]
        mock_docx.return_value = mock_doc

        mock_file = MagicMock()
        mock_file.name = "test.docx"

        content = parse_file_content(mock_file)
        self.assertIn("Docx Content", content)

    @patch("ai_assistant.utils.Image.open")
    @patch("ai_assistant.utils.pytesseract.image_to_string")
    def test_parse_image(self, mock_tesseract, mock_image_open):
        """Test parsing Image files (OCR)"""
        mock_tesseract.return_value = "OCR Content"

        mock_file = MagicMock()
        mock_file.name = "test.png"

        content = parse_file_content(mock_file)
        self.assertIn("OCR Content", content)

    @patch("ai_assistant.utils.Image.open")
    @patch("ai_assistant.utils.pytesseract.image_to_string")
    def test_parse_image_fail(self, mock_tesseract, mock_image_open):
        """Test parsing Image files when OCR fails"""
        mock_tesseract.side_effect = Exception("OCR Error")

        mock_file = MagicMock()
        mock_file.name = "test.png"

        content = parse_file_content(mock_file)
        self.assertIn("服务器未安装OCR组件", content)

    def test_parse_text_file(self):
        """Test parsing text files"""
        mock_file = MagicMock()
        mock_file.name = "test.txt"
        mock_file.read.return_value = b"Text Content"

        content = parse_file_content(mock_file)
        self.assertIn("Text Content", content)

    @patch("ai_assistant.utils.chardet.detect")
    def test_parse_text_file_encoding(self, mock_detect):
        """Test parsing text files with different encoding"""
        mock_detect.return_value = {"encoding": "gbk"}
        mock_file = MagicMock()
        mock_file.name = "test.txt"
        # GBK encoded string
        mock_file.read.return_value = "中文内容".encode("gbk")

        content = parse_file_content(mock_file)
        self.assertIn("中文内容", content)

    def test_parse_unknown_exception(self):
        """Test general exception handling"""
        mock_file = MagicMock()
        mock_file.name = "test.txt"
        mock_file.read.side_effect = Exception("Read Error")

        content = parse_file_content(mock_file)
        self.assertIn("文件解析出错", content)
