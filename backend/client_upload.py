import requests
import os

BASE_URL = 'http://127.0.0.1:8000/api'
LOCAL_DATA_DIR = r'C:\Users\64149\Desktop\smartpaste_web\SmartPaste-Web\backend\test_data'

USER_DATA = {
    "username": "realuser",
    "password": "Password123!",
    "password2": "Password123!",
    "email": "real@test.com"
}

def get_token():
    # 尝试注册
    try:
        resp = requests.post(f'{BASE_URL}/accounts/register/', data=USER_DATA)
        if resp.status_code == 201:
            return resp.json()['token']
    except:
        pass
    # 尝试登录
    resp = requests.post(f'{BASE_URL}/accounts/login/', data={"username":USER_DATA["username"], "password":USER_DATA["password"]})
    if resp.status_code == 200:
        return resp.json()['token']
    print("❌ 无法获取Token")
    return None

def upload_config(token):
    print("\n>>> [1] 上传 Config.json")
    config_path = os.path.join(LOCAL_DATA_DIR, 'config.json')
    if not os.path.exists(config_path):
        return

    headers = {'Authorization': f'Token {token}'}
    with open(config_path, 'rb') as f:
        requests.post(f'{BASE_URL}/sync/config/', headers=headers, files={'file': f})

def sync_upload_files(token):
    print("\n>>> [2] 镜像同步 Files (上传新文件 + 删除云端旧文件)")
    files_root = os.path.join(LOCAL_DATA_DIR, 'files')
    headers = {'Authorization': f'Token {token}'}

    if not os.path.exists(files_root):
        print("未找到 files 文件夹")
        return

    # ==========================================
    # 第一步：获取云端现有的文件列表 (为了找出要删除谁)
    # ==========================================
    print("   正在获取云端列表...")
    try:
        resp = requests.get(f'{BASE_URL}/sync/files/', headers=headers)
        cloud_files = resp.json()
    except Exception as e:
        print(f"❌ 获取云端列表失败: {e}")
        return

    # 建立一个映射字典： { "相对路径": 数据库ID }
    # 用于后续通过 ID 删除文件
    cloud_map = {}
    for item in cloud_files:
        r_path = item.get('relative_path')
        if not r_path:
            r_path = os.path.basename(item['file'])
        
        # 统一把路径分隔符转为 /, 方便跨平台对比
        r_path = r_path.replace('\\', '/')
        cloud_map[r_path] = item['id']

    print(f"   云端现有 {len(cloud_map)} 个文件")

    # ==========================================
    # 第二步：上传本地文件，并记录本地有哪些文件
    # ==========================================
    local_paths_set = set() # 记录本地有的文件路径
    upload_count = 0

    for root, dirs, files in os.walk(files_root):
        for filename in files:
            if filename.endswith('.db'):
                continue
                
            full_path = os.path.join(root, filename)
            
            # 计算相对路径
            rel_path = os.path.relpath(full_path, files_root)
            # 统一转为 / 格式
            rel_path_web = rel_path.replace('\\', '/')
            
            # 加入本地集合
            local_paths_set.add(rel_path_web)

            # 这里为了简单，每次都上传覆盖（如果有MD5校验可以跳过未修改的文件）
            print(f"   ⬆️ 上传: {rel_path_web}")
            try:
                with open(full_path, 'rb') as f:
                    requests.post(
                        f'{BASE_URL}/sync/files/upload/', 
                        headers=headers, 
                        data={'relative_path': rel_path_web}, 
                        files={'file': f}
                    )
                    upload_count += 1
            except Exception as e:
                print(f"     ❌ 上传失败: {e}")

    # ==========================================
    # 第三步：对比并删除云端多余文件
    # ==========================================
    print("\n   正在清理云端多余文件...")
    delete_count = 0
    
    # 遍历云端列表
    for cloud_path, file_id in cloud_map.items():
        # 如果云端有，但本地集合里没有 -> 说明本地已经删了 -> 云端也要删
        if cloud_path not in local_paths_set:
            print(f"   🗑️ 删除云端旧文件: {cloud_path} (ID: {file_id})")
            try:
                del_resp = requests.delete(f'{BASE_URL}/sync/files/{file_id}/', headers=headers)
                if del_resp.status_code == 204:
                    delete_count += 1
                else:
                    print(f"     ❌ 删除失败: {del_resp.status_code}")
            except Exception as e:
                print(f"     ❌ 请求出错: {e}")

    print(f"\n✅ 镜像上传完成！")
    print(f"   - 上传/更新: {upload_count}")
    print(f"   - 云端删除: {delete_count}")

if __name__ == "__main__":
    token = get_token()
    if token:
        upload_config(token)
        sync_upload_files(token)