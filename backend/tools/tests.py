from django.test import TestCase
from django.core.management import call_command
from io import StringIO
from unittest.mock import patch


class DBManagerCommandTests(TestCase):
    def test_show_config(self):
        out = StringIO()
        call_command("dbmanager", "--show-config", stdout=out)
        self.assertIn("当前数据库配置", out.getvalue())

    @patch("tools.management.commands.dbmanager.connections")
    def test_test_connections(self, mock_connections):
        out = StringIO()
        # Mock connection and cursor
        mock_conn = mock_connections.__getitem__.return_value
        mock_cursor = mock_conn.cursor.return_value
        mock_cursor.fetchone.return_value = ["3.39.5"]  # SQLite version example

        call_command("dbmanager", "--test-connections", stdout=out)
        self.assertIn("测试数据库连接", out.getvalue())

    def test_show_tables_invalid_db(self):
        out = StringIO()
        call_command("dbmanager", "--show-tables", "invalid_db", stdout=out)
        self.assertIn('数据库 "invalid_db" 不存在', out.getvalue())

    @patch("tools.management.commands.dbmanager.connections")
    def test_show_tables_sqlite(self, mock_connections):
        out = StringIO()
        mock_conn = mock_connections.__getitem__.return_value
        mock_cursor = mock_conn.cursor.return_value

        call_command("dbmanager", "--show-tables", "default", stdout=out)
        # Just check if it tries to execute something, output might be empty if no tables mocked
        self.assertTrue(mock_cursor.execute.called)
