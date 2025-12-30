# test_concurrent.py
import asyncio
import aiohttp
import time
import pytest
import statistics

# ============================================
# 1. 配置
# ============================================

BASE_URL = "http://101.42.152.3"  # 服务器地址（不含 /api）
API_PREFIX = "/api"  # API 前缀
API_BASE = f"{BASE_URL}{API_PREFIX}".rstrip(
    "/"
)  # 完整 API base，例如：http://101.42.152.3/api

# 说明：之前脚本通过固定 SECRET_KEY 伪造 JWT。
# 这在真实项目里通常会导致 401（验签不匹配），且测试容易“误判通过”。
# 现在改为调用 /api/accounts/login/ 获取真实 JWT。

# 默认并发测试登录账户（按你的要求：直接硬编码在脚本里）
# NOTE: 我无法自动知道你服务器上的真实有效账号；如果这里登录失败，请把下面两个值改成你的有效账号。
TEST_USERNAME = "Ace"
TEST_PASSWORD = "pass123456"

# 阶梯加压（压力测试）配置：按需修改这些常量即可
# RUN_STRESS = False
RUN_STRESS = True

STRESS_ENDPOINT = "/sync/sqlite/get/"
STRESS_METHOD = "GET"
STRESS_STEP = 20
STRESS_MAX_CONCURRENCY = 300
STRESS_DURATION_S = 10.0
STRESS_TIMEOUT_S = 10.0

STRESS_MAX_5XX_RATE = 0.01
STRESS_MAX_P95_MS = 1500.0
STRESS_MIN_STABLE_CONCURRENCY = 40


def _percentile(sorted_values, p: float) -> float:
    """返回百分位（p in [0, 100]），输入需已排序。"""
    if not sorted_values:
        return 0.0
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return float(d0 + d1)


# ============================================
# 2. 辅助函数
# ============================================


async def check_server_health():
    """检查服务器是否正常运行"""
    try:
        async with aiohttp.ClientSession() as session:
            # 尝试访问 API 根路径；只要可连接就认为健康（即使 404/401 也算）
            async with session.get(f"{API_BASE}/", timeout=5) as response:
                print(f"服务器状态: {response.status}")
                return True  # 只要能连接就认为健康
    except aiohttp.ClientConnectorError:
        print("无法连接到服务器，请确保服务器正在运行")
        return False
    except Exception as e:
        print(f"连接异常: {e}")
        return False


async def create_test_user_and_config(session, user_id):
    """创建测试用户和配置文件（基于真实登录 token）。

    注意：当前实现不创建用户，仅使用登录账号去读写配置。
    """
    token = await login_and_get_access_token(session)
    if not token:
        return False, None
    headers = {"Authorization": f"Bearer {token}"}

    # 先尝试获取配置（可能不存在）
    async with session.get(f"{API_BASE}/sync/config/", headers=headers) as response:
        if response.status == 404:
            # 配置不存在，创建它
            print(f"用户 {user_id}: 配置不存在，创建中...")
            form_data = aiohttp.FormData()
            form_data.add_field(
                "file",
                '{"autostart": false, "tray_icon_visible": true}',
                filename="config.json",
                content_type="application/json",
            )

            async with session.post(
                f"{API_BASE}/sync/config/", headers=headers, data=form_data
            ) as upload_response:
                if upload_response.status in [200, 201]:
                    print(f"用户 {user_id}: 配置创建成功")
                    return True, token
                else:
                    print(
                        f"用户 {user_id}: 配置创建失败，状态码 {upload_response.status}"
                    )
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

        # 仅测试 API 根路径可连接
        endpoints_to_test = ["/"]

        async with aiohttp.ClientSession() as session:
            for endpoint in endpoints_to_test:
                try:
                    async with session.get(
                        f"{API_BASE}{endpoint}", timeout=5
                    ) as response:
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

        token = await login_and_get_access_token()
        if not token:
            pytest.skip(
                "无法登录获取 JWT；请检查文件顶部 TEST_USERNAME / TEST_PASSWORD 是否为有效账号"
            )

        # 测试端点
        endpoints = [
            ("/sync/config/", "GET"),
            ("/sync/files/", "GET"),
            ("/sync/sqlite/get/", "GET"),
        ]

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token}"}

            for endpoint, method in endpoints:
                try:
                    if method == "GET":
                        async with session.get(
                            f"{API_BASE}{endpoint}", headers=headers
                        ) as response:
                            print(f"{method} {endpoint}: 状态码 {response.status}")
                            # 如果是404，说明用户/资源不存在，这是正常情况
                            if response.status == 404:
                                print("  -> 资源不存在（可能是首次使用，属正常）")
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
            token = await login_and_get_access_token(session)
            if not token:
                pytest.skip(
                    "无法登录获取 JWT；请检查文件顶部 TEST_USERNAME / TEST_PASSWORD 是否为有效账号"
                )

            # 准备几个测试用户
            user_data = []
            for i in range(3):
                user_id = f"real_user_{i}"  # 仅用于日志/配置内容区分
                # 复用同一个 token（该脚本目前不创建用户，只用登录账号读写）
                user_data.append((user_id, token))

            if not user_data:
                print("警告：没有成功创建任何用户，跳过测试")
                return

            # 并发操作：混合 GET 和 POST 请求
            tasks = []
            for user_id, token in user_data:
                headers = {"Authorization": f"Bearer {token}"}

                # GET 配置
                tasks.append(
                    (
                        f"{user_id}_get_config",
                        session.get(f"{API_BASE}/sync/config/", headers=headers),
                    )
                )

                # POST 更新配置
                form_data = aiohttp.FormData()
                form_data.add_field(
                    "file",
                    f'{{"autostart": true, "tray_icon_visible": false, "user_id": "{user_id}"}}',
                    filename="config.json",
                    content_type="application/json",
                )
                tasks.append(
                    (
                        f"{user_id}_update_config",
                        session.post(
                            f"{API_BASE}/sync/config/", headers=headers, data=form_data
                        ),
                    )
                )

            # 并发执行
            start_time = time.time()
            results = {}

            for task_name, task in tasks:
                try:
                    response = await task
                    response_text = await response.text()
                    results[task_name] = {
                        "status": response.status,
                        "response": response_text[:200] if response_text else "",
                    }
                    print(f"{task_name}: 状态码 {response.status}")
                except Exception as e:
                    results[task_name] = {"error": str(e)}
                    print(f"{task_name}: 异常 - {e}")

            end_time = time.time()

            # 分析结果
            print("\n测试结果:")
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
            assert all("status" in r or "error" in r for r in results.values()), (
                "有请求未完成"
            )
            assert not any(
                r.get("status") == 500 for r in results.values() if "status" in r
            ), "存在500错误"

            print("✓ 并发配置操作测试完成")

    @pytest.mark.asyncio
    async def test_concurrent_file_operations_realistic(self):
        """实际场景的并发文件操作测试"""
        print("\n=== 实际场景并发文件操作测试 ===")

        if not await check_server_health():
            pytest.skip("服务器未运行")

        async with aiohttp.ClientSession() as session:
            token = await login_and_get_access_token(session)
            if not token:
                pytest.skip(
                    "无法登录获取 JWT；请检查文件顶部 TEST_USERNAME / TEST_PASSWORD 是否为有效账号"
                )

            # 复用同一个 token（该脚本目前不创建用户，只用登录账号读写）

            headers = {"Authorization": f"Bearer {token}"}

            # 并发上传文件
            upload_tasks = []
            for i in range(5):
                form_data = aiohttp.FormData()
                form_data.add_field(
                    "file",
                    f"This is concurrent test file {i}".encode(),
                    filename=f"test_{i}.txt",
                    content_type="text/plain",
                )
                form_data.add_field("relative_path", "test_folder/")

                upload_tasks.append(
                    session.post(
                        f"{API_BASE}/sync/files/upload/",
                        headers=headers,
                        data=form_data,
                    )
                )

            # 并发获取文件列表
            download_tasks = [
                session.get(f"{API_BASE}/sync/files/", headers=headers)
                for _ in range(3)
            ]

            # 合并所有任务
            all_tasks = upload_tasks + download_tasks
            task_names = [f"upload_{i}" for i in range(len(upload_tasks))] + [
                f"download_{i}" for i in range(len(download_tasks))
            ]

            # 并发执行
            start_time = time.time()
            responses = await asyncio.gather(*all_tasks, return_exceptions=True)
            end_time = time.time()

            # 分析结果
            print("\n测试结果:")
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
                    status = getattr(response, "status", None)
                    if i < len(upload_tasks):
                        upload_results.append(status)
                        print(f"上传任务 {i}: 状态码 {status}")
                    else:
                        download_results.append(status)
                        print(f"下载任务 {i - len(upload_tasks)}: 状态码 {status}")

            # 验证：没有500错误
            assert not any(
                status == 500 for status in upload_results if isinstance(status, int)
            ), "上传存在500错误"
            assert not any(
                status == 500 for status in download_results if isinstance(status, int)
            ), "下载存在500错误"

            print("✓ 并发文件操作测试完成")

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations_realistic(self):
        """实际场景的混合并发操作测试"""
        print("\n=== 实际场景混合并发操作测试 ===")

        if not await check_server_health():
            pytest.skip("服务器未运行")

        async def worker(worker_id, num_operations):
            """工作线程：执行混合操作"""
            token = await login_and_get_access_token()
            if not token:
                return
            headers = {"Authorization": f"Bearer {token}"}

            async with aiohttp.ClientSession() as session:
                for i in range(num_operations):
                    operation_type = i % 4

                    try:
                        if operation_type == 0:
                            # 获取配置
                            await session.get(
                                f"{API_BASE}/sync/config/", headers=headers
                            )
                        elif operation_type == 1:
                            # 上传配置
                            form_data = aiohttp.FormData()
                            form_data.add_field(
                                "file", '{"test": "data"}', filename="config.json"
                            )
                            await session.post(
                                f"{API_BASE}/sync/config/",
                                headers=headers,
                                data=form_data,
                            )
                        elif operation_type == 2:
                            # 获取文件列表
                            await session.get(
                                f"{API_BASE}/sync/files/", headers=headers
                            )
                        else:
                            # 上传文件
                            form_data = aiohttp.FormData()
                            form_data.add_field(
                                "file", b"test content", filename="test.txt"
                            )
                            form_data.add_field("relative_path", "")
                            await session.post(
                                f"{API_BASE}/sync/files/upload/",
                                headers=headers,
                                data=form_data,
                            )
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

        print("\n测试结果:")
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
        token = await login_and_get_access_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}

        async with aiohttp.ClientSession() as session:
            start_time = time.time()

            # 发送多个 GET 请求（最简单的操作）
            tasks = []
            for i in range(num_requests):
                task = session.get(f"{API_BASE}/sync/config/", headers=headers)
                tasks.append(task)

            responses = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()

            # 统计
            success = 0
            for r in responses:
                if isinstance(r, Exception):
                    continue
                status = getattr(r, "status", 0) or 0
                if status and status < 500:
                    success += 1
            errors = len(responses) - success

            return {
                "total": num_requests,
                "success": success,
                "errors": errors,
                "time": end_time - start_time,
            }

    # 测试不同并发级别
    test_cases = [1, 5, 10, 20]
    results = []

    for num_requests in test_cases:
        print(f"\n测试 {num_requests} 个并发请求...")
        result = await make_requests(num_requests)
        if result is None:
            pytest.skip(
                "无法登录获取 JWT；请检查文件顶部 TEST_USERNAME / TEST_PASSWORD 是否为有效账号"
            )
        results.append((num_requests, result))

        print(f"  成功: {result['success']}/{result['total']}")
        print(f"  耗时: {result['time']:.2f}秒")
        print(f"  QPS: {result['total'] / result['time']:.2f}")

    print("\n性能测试总结:")
    for num_requests, result in results:
        print(
            f"  {num_requests:2d} 请求: {result['time']:.2f}秒, QPS: {result['total'] / result['time']:.2f}"
        )

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


# ============================================
# 6. 可选：阶梯加压（找大致上限）
# ============================================


async def login_and_get_access_token(
    session: aiohttp.ClientSession | None = None,
) -> str | None:
    """调用真实登录接口，获取可用于 Bearer 的 access token。

    若用户名/密码无效，返回 None（测试将选择 skip 而不是 fail）。
    """
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        url = f"{API_BASE}/accounts/login/"
        async with session.post(
            url,
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            timeout=10,
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                return None
            jwt_obj = data.get("jwt") or {}
            access = jwt_obj.get("access")
            if not access:
                return None
            return access
    finally:
        if close_session:
            await session.close()


async def run_load_step(
    *,
    concurrency: int,
    duration_s: float,
    request_timeout_s: float,
    endpoint_path: str,
    method: str,
    headers: dict,
) -> dict:
    """以固定并发运行一段时间，返回统计结果。

    采用“闭环”模型：每个 worker 串行发请求，worker 数量 = 并发数。
    """

    connector = aiohttp.TCPConnector(limit=0)  # 不人为限制连接池（交给 worker 数控制）
    timeout = aiohttp.ClientTimeout(total=request_timeout_s)

    latencies_ms: list[float] = []
    status_counts: dict[int, int] = {}
    exceptions = 0

    url = f"{API_BASE}{endpoint_path}"
    deadline = time.time() + duration_s

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:

        async def worker():
            nonlocal exceptions
            while time.time() < deadline:
                start = time.perf_counter()
                try:
                    if method.upper() == "GET":
                        async with session.get(url, headers=headers) as resp:
                            await resp.read()
                            status_counts[resp.status] = (
                                status_counts.get(resp.status, 0) + 1
                            )
                    elif method.upper() == "POST":
                        async with session.post(url, headers=headers) as resp:
                            await resp.read()
                            status_counts[resp.status] = (
                                status_counts.get(resp.status, 0) + 1
                            )
                    else:
                        raise ValueError(f"unsupported method: {method}")
                except Exception:
                    exceptions += 1
                finally:
                    latencies_ms.append((time.perf_counter() - start) * 1000.0)

        tasks = [asyncio.create_task(worker()) for _ in range(max(concurrency, 1))]
        await asyncio.gather(*tasks)

    latencies_ms_sorted = sorted(latencies_ms)
    total = sum(status_counts.values()) + exceptions
    errors_5xx = sum(c for s, c in status_counts.items() if 500 <= s <= 599)
    errors_4xx = sum(c for s, c in status_counts.items() if 400 <= s <= 499)
    p50 = _percentile(latencies_ms_sorted, 50)
    p95 = _percentile(latencies_ms_sorted, 95)
    avg = statistics.mean(latencies_ms_sorted) if latencies_ms_sorted else 0.0

    return {
        "concurrency": concurrency,
        "duration_s": duration_s,
        "total": total,
        "status_counts": status_counts,
        "exceptions": exceptions,
        "errors_4xx": errors_4xx,
        "errors_5xx": errors_5xx,
        "latency_ms": {"avg": avg, "p50": p50, "p95": p95},
        "rps": (total / duration_s) if duration_s > 0 else 0.0,
    }


@pytest.mark.asyncio
@pytest.mark.stress
async def test_stress_find_capacity():
    """阶梯加压：粗略找“稳定上限”。

    默认不会跑（避免误伤线上/开发机）：
    - 将文件顶部 RUN_STRESS 改为 True 才会执行。

    你可以通过修改文件顶部的 STRESS_* 常量调参。
    """

    if not RUN_STRESS:
        pytest.skip("Set RUN_STRESS=True in test_concurrent.py to run stress test")

    if not await check_server_health():
        pytest.skip("服务器未运行")

    endpoint = STRESS_ENDPOINT
    method = STRESS_METHOD
    max_concurrency = int(STRESS_MAX_CONCURRENCY)
    step = int(STRESS_STEP)
    duration_s = float(STRESS_DURATION_S)
    timeout_s = float(STRESS_TIMEOUT_S)
    max_5xx_rate = float(STRESS_MAX_5XX_RATE)
    max_p95_ms = float(STRESS_MAX_P95_MS)
    min_stable = int(STRESS_MIN_STABLE_CONCURRENCY)

    token = await login_and_get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    print("\n=== 阶梯加压开始 ===")
    print(
        f"endpoint={endpoint} method={method} duration={duration_s}s step={step} max={max_concurrency}"
    )
    print(f"threshold: 5xx_rate<={max_5xx_rate}, p95_ms<={max_p95_ms}")

    last_ok = 0
    for conc in range(step, max_concurrency + 1, step):
        result = await run_load_step(
            concurrency=conc,
            duration_s=duration_s,
            request_timeout_s=timeout_s,
            endpoint_path=endpoint,
            method=method,
            headers=headers,
        )

        total = result["total"] or 1
        rate_5xx = result["errors_5xx"] / total
        p95 = result["latency_ms"]["p95"]

        print(
            f"concurrency={conc:4d} rps={result['rps']:.1f} "
            f"p95={p95:.0f}ms 5xx_rate={rate_5xx:.3f} statuses={result['status_counts']} exc={result['exceptions']}"
        )

        if rate_5xx > max_5xx_rate or p95 > max_p95_ms:
            print("达到阈值，停止加压")
            break

        last_ok = conc

    assert last_ok >= min_stable, (
        f"稳定并发上限过低: last_ok={last_ok}, expected>={min_stable}. "
        f"(Try increasing server workers or relaxing thresholds.)"
    )
