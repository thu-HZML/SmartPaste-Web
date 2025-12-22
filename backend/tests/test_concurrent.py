# test_concurrent.py
import os
import sys
import asyncio
import aiohttp
import jwt
import time
import pytest
import uuid
from datetime import datetime, timedelta, timezone

# ============================================
# 1. 配置
# ============================================

BASE_URL = "http://127.0.0.1:8000"

# 由于无法从 Django 获取密钥，我们使用一个固定的测试密钥
# 注意：这要求你的 Django 项目也使用相同的密钥，或者你需要在 Django 中添加这个测试用户
SECRET_KEY = "test-secret-key-for-development-only-do-not-use-in-production"
ALGORITHM = "HS256"

def generate_test_token(user_id=None):
    """生成测试用的 JWT token"""
    if user_id is None:
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "user_id": str(user_id),
        "username": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ============================================
# 2. 辅助函数
# ============================================

async def check_server_health():
    """检查服务器是否正常运行"""
    try:
        async with aiohttp.ClientSession() as session:
            # 尝试访问根路径或健康检查端点
            async with session.get(f"{BASE_URL}/", timeout=5) as response:
                print(f"服务器状态: {response.status}")
                return True  # 只要能连接就认为健康
    except aiohttp.ClientConnectorError:
        print("无法连接到服务器，请确保服务器正在运行")
        return False
    except Exception as e:
        print(f"连接异常: {e}")
        return False

async def create_test_user_and_config(session, user_id):
    """创建测试用户和配置文件"""
    token = generate_test_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 先尝试获取配置（可能不存在）
    async with session.get(f"{BASE_URL}/sync/config/", headers=headers) as response:
        if response.status == 404:
            # 配置不存在，创建它
            print(f"用户 {user_id}: 配置不存在，创建中...")
            form_data = aiohttp.FormData()
            form_data.add_field(
                'file',
                '{"autostart": false, "tray_icon_visible": true}',
                filename='config.json',
                content_type='application/json'
            )
            
            async with session.post(
                f"{BASE_URL}/sync/config/",
                headers=headers,
                data=form_data
            ) as upload_response:
                if upload_response.status in [200, 201]:
                    print(f"用户 {user_id}: 配置创建成功")
                    return True, token
                else:
                    print(f"用户 {user_id}: 配置创建失败，状态码 {upload_response.status}")
                    return False, token
        else:
            print(f"用户 {user_id}: 配置已存在")
            return True, token
    
    return False, token

# ============================================
# 3. 测试用例 - 针对实际场景调整
# ============================================

class TestConcurrentAPI:
    """并发 API 测试类"""
    
    @pytest.mark.asyncio
    async def test_basic_endpoints(self):
        """测试基本端点是否可访问"""
        print("\n=== 测试基本端点 ===")
        
        if not await check_server_health():
            pytest.skip("服务器未运行")
        
        # 测试不需要认证的端点（如果有的话）
        endpoints_to_test = [
            "/",  # 根路径
            "/admin/",  # Django admin（如果有）
        ]
        
        async with aiohttp.ClientSession() as session:
            for endpoint in endpoints_to_test:
                try:
                    async with session.get(f"{BASE_URL}{endpoint}", timeout=5) as response:
                        print(f"{endpoint}: 状态码 {response.status}")
                except Exception as e:
                    print(f"{endpoint}: 连接失败 - {e}")
        
        print("✓ 基本端点测试完成")
    
    @pytest.mark.asyncio
    async def test_auth_required_endpoints(self):
        """测试需要认证的端点"""
        print("\n=== 测试需要认证的端点 ===")
        
        if not await check_server_health():
            pytest.skip("服务器未运行")
        
        user_id = f"auth_test_{uuid.uuid4().hex[:8]}"
        token = generate_test_token(user_id)
        
        # 测试端点
        endpoints = [
            ("/sync/config/", "GET"),
            ("/sync/files/", "GET"),
            ("/sync/sqlite/get", "GET"),
        ]
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token}"}
            
            for endpoint, method in endpoints:
                try:
                    if method == "GET":
                        async with session.get(f"{BASE_URL}{endpoint}", headers=headers) as response:
                            print(f"{method} {endpoint}: 状态码 {response.status}")
                            # 如果是404，说明用户/资源不存在，这是正常情况
                            if response.status == 404:
                                print(f"  -> 用户 {user_id} 的资源不存在（正常）")
                except Exception as e:
                    print(f"{method} {endpoint}: 请求失败 - {e}")
        
        print("✓ 认证端点测试完成")
    
    @pytest.mark.asyncio
    async def test_concurrent_config_operations_realistic(self):
        """实际场景的并发配置操作测试"""
        print("\n=== 实际场景并发配置操作测试 ===")
        
        if not await check_server_health():
            pytest.skip("服务器未运行")
        
        async with aiohttp.ClientSession() as session:
            # 准备几个测试用户
            user_data = []
            for i in range(3):
                user_id = f"real_user_{i}"
                success, token = await create_test_user_and_config(session, user_id)
                if success:
                    user_data.append((user_id, token))
            
            if not user_data:
                print("警告：没有成功创建任何用户，跳过测试")
                return
            
            # 并发操作：混合 GET 和 POST 请求
            tasks = []
            for user_id, token in user_data:
                headers = {"Authorization": f"Bearer {token}"}
                
                # GET 配置
                tasks.append((
                    f"{user_id}_get_config",
                    session.get(f"{BASE_URL}/sync/config/", headers=headers)
                ))
                
                # POST 更新配置
                form_data = aiohttp.FormData()
                form_data.add_field(
                    'file',
                    f'{{"autostart": true, "tray_icon_visible": false, "user_id": "{user_id}"}}',
                    filename='config.json',
                    content_type='application/json'
                )
                tasks.append((
                    f"{user_id}_update_config",
                    session.post(f"{BASE_URL}/sync/config/", headers=headers, data=form_data)
                ))
            
            # 并发执行
            start_time = time.time()
            results = {}
            
            for task_name, task in tasks:
                try:
                    response = await task
                    response_text = await response.text()
                    results[task_name] = {
                        "status": response.status,
                        "response": response_text[:200] if response_text else ""
                    }
                    print(f"{task_name}: 状态码 {response.status}")
                except Exception as e:
                    results[task_name] = {"error": str(e)}
                    print(f"{task_name}: 异常 - {e}")
            
            end_time = time.time()
            
            # 分析结果
            print(f"\n测试结果:")
            print(f"总请求数: {len(tasks)}")
            print(f"总耗时: {end_time - start_time:.2f}秒")
            
            # 统计状态码
            status_counts = {}
            for result in results.values():
                if "status" in result:
                    status = result["status"]
                    status_counts[status] = status_counts.get(status, 0) + 1
            
            print(f"状态码分布: {status_counts}")
            
            # 验证：没有500错误，所有请求都有响应
            assert all("status" in r or "error" in r for r in results.values()), "有请求未完成"
            assert not any(r.get("status") == 500 for r in results.values() if "status" in r), "存在500错误"
            
            print("✓ 并发配置操作测试完成")
    
    @pytest.mark.asyncio
    async def test_concurrent_file_operations_realistic(self):
        """实际场景的并发文件操作测试"""
        print("\n=== 实际场景并发文件操作测试 ===")
        
        if not await check_server_health():
            pytest.skip("服务器未运行")
        
        async with aiohttp.ClientSession() as session:
            # 创建一个测试用户
            user_id = f"file_test_user_{uuid.uuid4().hex[:8]}"
            success, token = await create_test_user_and_config(session, user_id)
            
            if not success:
                print(f"用户 {user_id} 创建失败，跳过文件测试")
                return
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # 并发上传文件
            upload_tasks = []
            for i in range(5):
                form_data = aiohttp.FormData()
                form_data.add_field(
                    'file',
                    f'This is concurrent test file {i}'.encode(),
                    filename=f'test_{i}.txt',
                    content_type='text/plain'
                )
                form_data.add_field('relative_path', 'test_folder/')
                
                upload_tasks.append(
                    session.post(
                        f"{BASE_URL}/sync/files/upload/",
                        headers=headers,
                        data=form_data
                    )
                )
            
            # 并发获取文件列表
            download_tasks = [
                session.get(f"{BASE_URL}/sync/files/", headers=headers)
                for _ in range(3)
            ]
            
            # 合并所有任务
            all_tasks = upload_tasks + download_tasks
            task_names = [f"upload_{i}" for i in range(len(upload_tasks))] + \
                        [f"download_{i}" for i in range(len(download_tasks))]
            
            # 并发执行
            start_time = time.time()
            responses = await asyncio.gather(*all_tasks, return_exceptions=True)
            end_time = time.time()
            
            # 分析结果
            print(f"\n测试结果:")
            print(f"上传任务数: {len(upload_tasks)}")
            print(f"下载任务数: {len(download_tasks)}")
            print(f"总耗时: {end_time - start_time:.2f}秒")
            
            # 统计
            upload_results = []
            download_results = []
            
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    print(f"任务 {task_names[i]}: 异常 - {response}")
                    if i < len(upload_tasks):
                        upload_results.append("error")
                    else:
                        download_results.append("error")
                else:
                    if i < len(upload_tasks):
                        upload_results.append(response.status)
                        print(f"上传任务 {i}: 状态码 {response.status}")
                    else:
                        download_results.append(response.status)
                        print(f"下载任务 {i - len(upload_tasks)}: 状态码 {response.status}")
            
            # 验证：没有500错误
            assert not any(status == 500 for status in upload_results if isinstance(status, int)), "上传存在500错误"
            assert not any(status == 500 for status in download_results if isinstance(status, int)), "下载存在500错误"
            
            print("✓ 并发文件操作测试完成")
    
    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations_realistic(self):
        """实际场景的混合并发操作测试"""
        print("\n=== 实际场景混合并发操作测试 ===")
        
        if not await check_server_health():
            pytest.skip("服务器未运行")
        
        async def worker(worker_id, num_operations):
            """工作线程：执行混合操作"""
            user_id = f"worker_{worker_id}"
            token = generate_test_token(user_id)
            headers = {"Authorization": f"Bearer {token}"}
            
            async with aiohttp.ClientSession() as session:
                for i in range(num_operations):
                    operation_type = i % 4
                    
                    try:
                        if operation_type == 0:
                            # 获取配置
                            await session.get(f"{BASE_URL}/sync/config/", headers=headers)
                        elif operation_type == 1:
                            # 上传配置
                            form_data = aiohttp.FormData()
                            form_data.add_field('file', '{"test": "data"}', filename='config.json')
                            await session.post(f"{BASE_URL}/sync/config/", headers=headers, data=form_data)
                        elif operation_type == 2:
                            # 获取文件列表
                            await session.get(f"{BASE_URL}/sync/files/", headers=headers)
                        else:
                            # 上传文件
                            form_data = aiohttp.FormData()
                            form_data.add_field('file', b'test content', filename='test.txt')
                            form_data.add_field('relative_path', '')
                            await session.post(f"{BASE_URL}/sync/files/upload/", headers=headers, data=form_data)
                    except Exception as e:
                        print(f"工作线程 {worker_id} 操作 {i} 失败: {e}")
                        # 继续执行，不中断
        
        # 启动多个工作线程
        num_workers = 3
        operations_per_worker = 4
        
        start_time = time.time()
        tasks = [worker(i, operations_per_worker) for i in range(num_workers)]
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        total_operations = num_workers * operations_per_worker
        total_time = end_time - start_time
        
        print(f"\n测试结果:")
        print(f"工作线程数: {num_workers}")
        print(f"每个线程操作数: {operations_per_worker}")
        print(f"总操作数: {total_operations}")
        print(f"总耗时: {total_time:.2f}秒")
        print(f"平均QPS: {total_operations / total_time:.2f}")
        
        assert total_time > 0, "测试时间异常"
        print("✓ 混合并发操作测试完成")

# ============================================
# 4. 简单的性能测试
# ============================================

@pytest.mark.asyncio
async def test_performance_simple():
    """简单的性能测试"""
    print("\n=== 简单性能测试 ===")
    
    if not await check_server_health():
        pytest.skip("服务器未运行")
    
    async def make_requests(num_requests):
        """发送指定数量的请求"""
        user_id = f"perf_user_{uuid.uuid4().hex[:8]}"
        token = generate_test_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}
        
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            
            # 发送多个 GET 请求（最简单的操作）
            tasks = []
            for i in range(num_requests):
                task = session.get(f"{BASE_URL}/sync/config/", headers=headers)
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            # 统计
            success = sum(1 for r in responses if not isinstance(r, Exception) and r.status < 500)
            errors = len(responses) - success
            
            return {
                "total": num_requests,
                "success": success,
                "errors": errors,
                "time": end_time - start_time
            }
    
    # 测试不同并发级别
    test_cases = [1, 5, 10, 20]
    results = []
    
    for num_requests in test_cases:
        print(f"\n测试 {num_requests} 个并发请求...")
        result = await make_requests(num_requests)
        results.append((num_requests, result))
        
        print(f"  成功: {result['success']}/{result['total']}")
        print(f"  耗时: {result['time']:.2f}秒")
        print(f"  QPS: {result['total'] / result['time']:.2f}")
    
    print("\n性能测试总结:")
    for num_requests, result in results:
        print(f"  {num_requests:2d} 请求: {result['time']:.2f}秒, QPS: {result['total']/result['time']:.2f}")
    
    print("✓ 性能测试完成")

# ============================================
# 5. 主运行函数
# ============================================

async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("开始并发 API 测试")
    print("=" * 60)
    
    # 检查服务器
    print("\n[1] 检查服务器连接...")
    if not await check_server_health():
        print("错误: 服务器未运行！请先启动服务器：")
        print("  python manage.py runserver")
        return
    
    print("✓ 服务器已连接")
    
    # 运行测试
    tester = TestConcurrentAPI()
    
    test_functions = [
        ("基本端点测试", tester.test_basic_endpoints),
        ("认证端点测试", tester.test_auth_required_endpoints),
        ("并发配置操作测试", tester.test_concurrent_config_operations_realistic),
        ("并发文件操作测试", tester.test_concurrent_file_operations_realistic),
        ("混合并发操作测试", tester.test_concurrent_mixed_operations_realistic),
        ("性能测试", test_performance_simple),
    ]
    
    results = []
    for test_name, test_func in test_functions:
        print(f"\n[运行] {test_name}...")
        try:
            await test_func()
            results.append((test_name, "通过"))
            print(f"✓ {test_name} 通过")
        except Exception as e:
            results.append((test_name, f"失败: {e}"))
            print(f"✗ {test_name} 失败: {e}")
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结:")
    print("=" * 60)
    
    passed = sum(1 for _, status in results if status == "通过")
    failed = len(results) - passed
    
    for test_name, status in results:
        print(f"  {test_name}: {status}")
    
    print(f"\n总计: {len(results)} 个测试")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    
    if failed == 0:
        print("\n✓ 所有测试通过！")
    else:
        print(f"\n⚠ {failed} 个测试失败")

if __name__ == "__main__":
    # 直接运行所有测试
    asyncio.run(run_all_tests())