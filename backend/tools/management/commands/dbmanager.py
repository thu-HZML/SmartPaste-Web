"""
数据库切换管理工具
提供多种数据库切换和操作的便捷方法
"""

from django.core.management.base import BaseCommand
from django.db import connections
from django.conf import settings
import os


class Command(BaseCommand):
    help = "数据库管理工具 - 切换、查看、测试数据库连接"

    def add_arguments(self, parser):
        parser.add_argument(
            "--show-config", action="store_true", help="显示当前数据库配置"
        )
        parser.add_argument(
            "--test-connections", action="store_true", help="测试所有数据库连接"
        )
        parser.add_argument(
            "--show-tables", type=str, help="显示指定数据库的表 (mysql/sqlite/default)"
        )
        parser.add_argument(
            "--switch-to", type=str, help="切换默认数据库到 mysql 或 sqlite"
        )
        parser.add_argument(
            "--migrate-to", type=str, help="迁移数据库到指定数据库 (mysql/sqlite)"
        )

    def handle(self, *args, **options):
        if options["show_config"]:
            self.show_database_config()
        elif options["test_connections"]:
            self.test_all_connections()
        elif options["show_tables"]:
            self.show_tables(options["show_tables"])
        elif options["switch_to"]:
            self.switch_database(options["switch_to"])
        elif options["migrate_to"]:
            self.migrate_to_database(options["migrate_to"])
        else:
            self.show_help()

    def show_database_config(self):
        """显示当前数据库配置"""
        self.stdout.write(self.style.SUCCESS("🔧 当前数据库配置:"))

        current_default = os.environ.get("DEFAULT_DATABASE", "mysql")
        self.stdout.write(f"   默认数据库类型: {current_default.upper()}")

        for db_name, db_config in settings.DATABASES.items():
            engine = db_config["ENGINE"].split(".")[-1]
            if engine == "mysql":
                info = f"MySQL - {db_config.get('HOST', 'localhost')}:{db_config.get('PORT', '3306')}/{db_config.get('NAME', 'N/A')}"
            elif engine == "sqlite3":
                info = f"SQLite - {db_config.get('NAME', 'N/A')}"
            else:
                info = f"Unknown - {engine}"

            marker = "→" if db_name == "default" else " "
            self.stdout.write(f"   {marker} {db_name}: {info}")

    def test_all_connections(self):
        """测试所有数据库连接"""
        self.stdout.write(self.style.SUCCESS("🔗 测试数据库连接:"))

        for db_name in settings.DATABASES.keys():
            try:
                conn = connections[db_name]
                cursor = conn.cursor()

                if "mysql" in settings.DATABASES[db_name]["ENGINE"]:
                    cursor.execute("SELECT VERSION();")
                    version = cursor.fetchone()[0]
                    self.stdout.write(f"   ✅ {db_name}: MySQL {version}")
                else:
                    cursor.execute("SELECT sqlite_version();")
                    version = cursor.fetchone()[0]
                    self.stdout.write(f"   ✅ {db_name}: SQLite {version}")

            except Exception as e:
                self.stdout.write(f"   ❌ {db_name}: 连接失败 - {str(e)}")

    def show_tables(self, db_name):
        """显示指定数据库的表"""
        try:
            if db_name not in settings.DATABASES:
                self.stdout.write(self.style.ERROR(f'❌ 数据库 "{db_name}" 不存在'))
                return

            conn = connections[db_name]
            cursor = conn.cursor()

            if "mysql" in settings.DATABASES[db_name]["ENGINE"]:
                cursor.execute("SHOW TABLES;")
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")

            tables = cursor.fetchall()

            self.stdout.write(self.style.SUCCESS(f'📊 数据库 "{db_name}" 中的表:'))
            for i, (table,) in enumerate(tables, 1):
                self.stdout.write(f"   {i:2d}. {table}")
            self.stdout.write(f"\n   总计: {len(tables)} 个表")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 查询失败: {str(e)}"))

    def switch_database(self, target_db):
        """切换默认数据库"""
        if target_db not in ["mysql", "sqlite"]:
            self.stdout.write(self.style.ERROR("❌ 只支持切换到 mysql 或 sqlite"))
            return

        # 更新环境变量文件
        env_file = os.path.join(settings.BASE_DIR, ".env")

        try:
            # 读取现有内容
            lines = []
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            # 更新或添加 DEFAULT_DATABASE
            found = False
            for i, line in enumerate(lines):
                if line.startswith("DEFAULT_DATABASE="):
                    lines[i] = f"DEFAULT_DATABASE={target_db}\n"
                    found = True
                    break

            if not found:
                lines.append(f"DEFAULT_DATABASE={target_db}\n")

            # 写回文件
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(lines)

            self.stdout.write(
                self.style.SUCCESS(f"✅ 已切换默认数据库到: {target_db.upper()}")
            )
            self.stdout.write("⚠️  请重启Django服务器以使更改生效")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 切换失败: {str(e)}"))

    def migrate_to_database(self, target_db):
        """迁移到指定数据库"""
        if target_db not in ["mysql", "sqlite"]:
            self.stdout.write(self.style.ERROR("❌ 只支持迁移到 mysql 或 sqlite"))
            return

        self.stdout.write(f"🔄 开始迁移到 {target_db.upper()}...")

        try:
            # 运行迁移命令
            from django.core.management import execute_from_command_line
            import sys

            old_argv = sys.argv
            sys.argv = ["manage.py", "migrate", "--database", target_db]
            execute_from_command_line(sys.argv)
            sys.argv = old_argv

            self.stdout.write(self.style.SUCCESS(f"✅ 成功迁移到 {target_db.upper()}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 迁移失败: {str(e)}"))

    def show_help(self):
        """显示帮助信息"""
        self.stdout.write(self.style.SUCCESS("📚 数据库管理工具使用说明:"))
        self.stdout.write("")
        self.stdout.write("查看配置:")
        self.stdout.write("  python manage.py dbmanager --show-config")
        self.stdout.write("")
        self.stdout.write("测试连接:")
        self.stdout.write("  python manage.py dbmanager --test-connections")
        self.stdout.write("")
        self.stdout.write("查看表:")
        self.stdout.write("  python manage.py dbmanager --show-tables mysql")
        self.stdout.write("  python manage.py dbmanager --show-tables sqlite")
        self.stdout.write("")
        self.stdout.write("切换数据库:")
        self.stdout.write("  python manage.py dbmanager --switch-to mysql")
        self.stdout.write("  python manage.py dbmanager --switch-to sqlite")
        self.stdout.write("")
        self.stdout.write("迁移数据库:")
        self.stdout.write("  python manage.py dbmanager --migrate-to mysql")
        self.stdout.write("  python manage.py dbmanager --migrate-to sqlite")
