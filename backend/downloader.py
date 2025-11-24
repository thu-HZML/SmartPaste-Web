import requests
import os
import shutil  # 用于删除非空文件夹（如果需要）

BASE_URL = 'http://127.0.0.1:8000/api'
# 下载保存位置 (模拟另一台电脑)
DOWNLOAD_DIR = r'C:\Users\64149\Desktop\smartpaste_web\SmartPaste-Web\backend\download_test_pc2'

USER_DATA = {
    "username": "realuser",
    "password": "Password123!",
    "password2": "Password123!",
    "email": "real@test.com"
}

def login():
    try:
        resp = requests.post(f'{BASE_URL}/accounts/login/', data=USER_DATA)
        if resp.status_code == 200:
            return resp.json()['token']
        print(f"❌ 登录失败: {resp.text}")
    except Exception as e:
        print(f"❌ 连接服务器失败: {e}")
    return None

def sync_data(token):
    headers = {'Authorization': f'Token {token}'}
    
    # ==========================
    # 1. 下载 Config
    # ==========================
    print(">>> [1/3] 下载 Config ...")
    try:
        resp = requests.get(f'{BASE_URL}/sync/config/', headers=headers)
        if resp.status_code == 200:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            with open(os.path.join(DOWNLOAD_DIR, 'config.json'), 'wb') as f:
                f.write(resp.content)
            print("  ✅ Config 下载成功")
        elif resp.status_code == 404:
             print("  ⚠️ 云端无 Config 文件")
        else:
            print(f"  ❌ Config 下载失败，状态码: {resp.status_code}")
    except Exception as e:
        print(f"  ❌ Config 请求出错: {e}")
            
    # ==========================
    # 2. 下载 Files
    # ==========================
    print("\n>>> [2/3] 获取文件列表并下载 ...")
    try:
        resp = requests.get(f'{BASE_URL}/sync/files/', headers=headers)
        files_list = resp.json()
    except Exception as e:
        print(f"❌ 获取列表失败: {e}")
        return
    
    files_dir = os.path.join(DOWNLOAD_DIR, 'files')
    
    # 🔥🔥🔥 修复 1: 初始化集合，用于记录云端有哪些文件
    server_paths = set()

    print(f"发现 {len(files_list)} 个文件，开始同步...")
    
    for item in files_list:
        # 获取相对路径
        rel_path = item.get('relative_path')
        if not rel_path:
             rel_path = os.path.basename(item['file'])

        # 统一路径分隔符 (Windows用反斜杠)，确保后续对比准确
        norm_rel_path = os.path.normpath(rel_path)
        
        # 🔥🔥🔥 修复 2: 将该文件加入“白名单”，稍后清理时要用到
        server_paths.add(norm_rel_path)

        # 构造本地绝对路径
        local_file_path = os.path.join(files_dir, norm_rel_path)
        
        # 确保父文件夹存在
        local_folder = os.path.dirname(local_file_path)
        if not os.path.exists(local_folder):
            os.makedirs(local_folder)
            print(f"  📂 创建文件夹: {local_folder}")

        # 下载文件
        file_url = item['file']
        if not file_url.startswith('http'):
            file_url = f"http://127.0.0.1:8000{file_url}"
            
        print(f"  ⬇️ 下载/更新: {norm_rel_path}")
        try:
            r = requests.get(file_url)
            with open(local_file_path, 'wb') as f:
                f.write(r.content)
        except Exception as e:
            print(f"  ❌ 下载失败 {norm_rel_path}: {e}")

    # ==========================
    # 3. 清理本地旧文件
    # ==========================
    print("\n>>> [3/3] 清理本地旧文件 ...")
    if not os.path.exists(files_dir):
        return

    # 遍历本地 files 文件夹
    for root, dirs, files in os.walk(files_dir, topdown=False):
        for filename in files:
            # 获取本地文件的完整路径
            full_path = os.path.join(root, filename)
            # 计算出相对路径 (相对于 files_dir)
            rel_path = os.path.relpath(full_path, files_dir)
            # 统一格式
            rel_path = os.path.normpath(rel_path)

            # 🔥🔥🔥 这里的 server_paths 现在已经有内容了
            # 如果本地文件 不在 云端列表里，说明是被删除的旧文件
            if rel_path not in server_paths:
                print(f"  🗑️ 删除旧文件: {rel_path}")
                try:
                    os.remove(full_path)
                except OSError as e:
                    print(f"    删除失败: {e}")

        # 清理空文件夹
        for dirname in dirs:
            dir_full_path = os.path.join(root, dirname)
            # 如果文件夹空了，就删掉
            if not os.listdir(dir_full_path):
                print(f"  📂 删除空文件夹: {dirname}")
                try:
                    os.rmdir(dir_full_path)
                except OSError:
                    pass

    print("\n✅ 全部同步完成 (镜像模式)")


if __name__ == "__main__":
    token = login()
    if token:
        sync_data(token)
        print("\n✅ 脚本运行结束")