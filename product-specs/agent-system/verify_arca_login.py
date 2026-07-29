"""
验证方舟 DevOps 平台登录可行性
- 尝试通过表单登录获取 session
- 验证登录后是否能访问 API
"""
import requests
import sys
from urllib.parse import urljoin

# 配置（后续移入配置文件）
ARCA_BASE_URL = "https://arca-devops.ingageapp.com"
LOGIN_URL = f"{ARCA_BASE_URL}/user/login"


def verify_login(username: str, password: str) -> dict:
    """
    验证登录是否可行
    返回: {"success": bool, "message": str, "session": session_or_none}
    """
    session = requests.Session()
    session.verify = False  # 如果有证书问题可临时关闭

    # 第一步：获取登录页面（获取 CSRF token）
    print(f"[1] 访问登录页面: {LOGIN_URL}")
    try:
        resp = session.get(LOGIN_URL, timeout=10, allow_redirects=True)
        print(f"    状态码: {resp.status_code}")
        print(f"    最终URL: {resp.url}")
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"无法访问登录页面: {e}", "session": None}

    # 尝试提取 CSRF token（Gitea 风格）
    csrf_token = None
    if '_csrf' in resp.text:
        import re
        match = re.search(r'name="_csrf"\s+content="([^"]+)"', resp.text)
        if not match:
            match = re.search(r'name="_csrf"\s+value="([^"]+)"', resp.text)
        if match:
            csrf_token = match.group(1)
            print(f"    CSRF Token: {csrf_token[:20]}...")

    # 第二步：提交登录表单
    print(f"\n[2] 提交登录请求...")
    login_data = {
        "user_name": username,
        "password": password,
    }
    if csrf_token:
        login_data["_csrf"] = csrf_token

    try:
        resp = session.post(
            LOGIN_URL,
            data=login_data,
            timeout=10,
            allow_redirects=True
        )
        print(f"    状态码: {resp.status_code}")
        print(f"    最终URL: {resp.url}")
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"登录请求失败: {e}", "session": None}

    # 第三步：判断登录是否成功
    # 通常登录成功会重定向到首页，失败会留在登录页
    if "/user/login" in resp.url:
        return {"success": False, "message": "登录失败 - 仍在登录页面（账号或密码错误）", "session": None}

    # 验证 session 是否有效 - 尝试访问 API
    print(f"\n[3] 验证 session 有效性...")
    try:
        # 尝试访问用户信息接口
        api_resp = session.get(f"{ARCA_BASE_URL}/api/v1/user", timeout=10)
        print(f"    API 状态码: {api_resp.status_code}")
        if api_resp.status_code == 200:
            user_info = api_resp.json()
            print(f"    用户名: {user_info.get('login', 'N/A')}")
            return {
                "success": True,
                "message": f"登录成功! 用户: {user_info.get('login', 'N/A')}",
                "session": session
            }
    except Exception as e:
        print(f"    API 验证异常: {e}")

    # 如果 API 不可用但已离开登录页，仍视为部分成功
    return {
        "success": True,
        "message": "登录可能成功（已离开登录页，但 API 验证未通过）",
        "session": session
    }


def check_cpu_monitoring_api(session: requests.Session) -> dict:
    """
    检查是否有 CPU 监控相关的 API 可用
    """
    print(f"\n[4] 探测 CPU 监控相关 API...")
    possible_endpoints = [
        "/api/v1/repos/search",  # 仓库搜索
        "/api/v1/admin/stats",   # 管理员统计
        "/-/api/metrics",        # Prometheus metrics
        "/metrics",              # 直接 metrics 端点
    ]

    results = {}
    for endpoint in possible_endpoints:
        url = f"{ARCA_BASE_URL}{endpoint}"
        try:
            resp = session.get(url, timeout=5)
            results[endpoint] = {
                "status": resp.status_code,
                "accessible": resp.status_code == 200
            }
            print(f"    {endpoint}: {resp.status_code}")
        except Exception as e:
            results[endpoint] = {"status": "error", "accessible": False}
            print(f"    {endpoint}: 错误 - {e}")

    return results


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 从命令行参数或环境变量读取凭据
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        import os
        username = os.environ.get("ARCA_USERNAME", "")
        password = os.environ.get("ARCA_PASSWORD", "")

    if not username or not password:
        print("用法: python verify_arca_login.py <username> <password>")
        print("或设置环境变量: ARCA_USERNAME, ARCA_PASSWORD")
        sys.exit(1)

    print("=" * 50)
    print("方舟 DevOps 登录验证")
    print("=" * 50)

    result = verify_login(username, password)
    print(f"\n{'=' * 50}")
    print(f"结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"信息: {result['message']}")

    if result["success"] and result["session"]:
        check_cpu_monitoring_api(result["session"])

    print(f"\n{'=' * 50}")
    print("结论:")
    if result["success"]:
        print("  ✅ 登录逻辑可行，可以集成到自动化流程中")
        print("  建议: 将凭据放入 .env 配置文件，使用 python-dotenv 加载")
    else:
        print("  ❌ 登录不可行，需检查:")
        print("     - 账号密码是否正确")
        print("     - 是否需要其他认证方式（OAuth/API Token）")
        print("     - 网络是否可达")
