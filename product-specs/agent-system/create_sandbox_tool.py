"""
创建腾讯云 Agent Runtime 沙箱工具 + 执行 Python 代码

使用方式:
  1. 填入腾讯云 SecretId / SecretKey（在 https://console.cloud.tencent.com/cam/capi 获取）
  2. 运行: python3 create_sandbox_tool.py

该脚本会:
  - 调用 CreateSandboxTool API 创建代码解释器沙箱工具
  - 然后用 E2B SDK 在沙箱中执行 Python 代码
"""
import os
import json

# ============ 配置区 ============
# 腾讯云主账号/子账号的 API 密钥（用于创建沙箱工具）
TENCENT_SECRET_ID = os.environ.get("TENCENT_SECRET_ID", "你的SecretId")
TENCENT_SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "你的SecretKey")

# Agent Runtime 沙箱 API Key（用于 E2B SDK 调用）
E2B_API_KEY = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"
E2B_DOMAIN = "ap-beijing.tencentags.com"

# 沙箱工具配置
TOOL_NAME = "code-interpreter-v1"
TOOL_TYPE = "code-interpreter"
REGION = "ap-beijing"
# ================================


def create_sandbox_tool():
    """通过腾讯云 API 创建沙箱工具"""
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

    try:
        # 动态导入 ags 模块
        from tencentcloud.ags.v20250920 import ags_client, models
    except ImportError:
        print("tencentcloud-sdk-python 未包含 ags 模块，尝试手动调用...")
        return create_sandbox_tool_raw()

    cred = credential.Credential(TENCENT_SECRET_ID, TENCENT_SECRET_KEY)

    httpProfile = HttpProfile()
    httpProfile.endpoint = "ags.tencentcloudapi.com"

    clientProfile = ClientProfile()
    clientProfile.httpProfile = httpProfile

    client = ags_client.AgsClient(cred, REGION, clientProfile)

    req = models.CreateSandboxToolRequest()
    params = {
        "ToolName": TOOL_NAME,
        "ToolType": TOOL_TYPE,
        "Description": "代码解释器沙箱工具",
        "DefaultTimeout": "1h",
        "NetworkConfiguration": {
            "NetworkMode": "PUBLIC"
        }
    }
    req.from_json_string(json.dumps(params))

    try:
        resp = client.CreateSandboxTool(req)
        print(f"沙箱工具创建成功! ToolId: {resp.ToolId}")
        return True
    except TencentCloudSDKException as e:
        if "已经存在" in str(e) or "DuplicateRequest" in str(e):
            print(f"沙箱工具 '{TOOL_NAME}' 已存在，跳过创建")
            return True
        print(f"创建沙箱工具失败: {e}")
        return False


def create_sandbox_tool_raw():
    """通过原始 HTTP 请求创建沙箱工具（备用方案）"""
    import hashlib
    import hmac
    import time
    from datetime import datetime, timezone
    import httpx

    service = "ags"
    host = "ags.tencentcloudapi.com"
    action = "CreateSandboxTool"
    version = "2025-09-20"
    algorithm = "TC3-HMAC-SHA256"

    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

    # 请求体
    payload = json.dumps({
        "ToolName": TOOL_NAME,
        "ToolType": TOOL_TYPE,
        "Description": "代码解释器沙箱工具",
        "DefaultTimeout": "1h",
        "NetworkConfiguration": {
            "NetworkMode": "PUBLIC"
        }
    })

    # 拼接规范请求串
    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"
    )

    # 拼接待签名字符串
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

    # 计算签名
    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = sign(("TC3" + TENCENT_SECRET_KEY).encode("utf-8"), date)
    secret_service = sign(secret_date, service)
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # 拼接 Authorization
    authorization = (
        f"{algorithm} Credential={TENCENT_SECRET_ID}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": REGION,
    }

    resp = httpx.post(f"https://{host}", headers=headers, content=payload, timeout=30)
    result = resp.json()
    print(f"API 响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

    if "Response" in result and "ToolId" in result["Response"]:
        print(f"沙箱工具创建成功! ToolId: {result['Response']['ToolId']}")
        return True
    elif "Error" in result.get("Response", {}):
        error = result["Response"]["Error"]
        if "已经存在" in error.get("Message", ""):
            print(f"沙箱工具 '{TOOL_NAME}' 已存在")
            return True
        print(f"创建失败: {error}")
        return False
    return False


def run_code_in_sandbox(code: str):
    """在沙箱中执行 Python 代码"""
    os.environ["E2B_DOMAIN"] = E2B_DOMAIN
    os.environ["E2B_API_KEY"] = E2B_API_KEY

    from e2b_code_interpreter import Sandbox

    print(f"\n正在创建沙箱实例 (template={TOOL_NAME})...")
    sandbox = Sandbox.create(template=TOOL_NAME, timeout=3600)
    print(f"沙箱已创建: {sandbox.sandbox_id}")

    try:
        print("执行代码中...\n" + "=" * 40)
        result = sandbox.run_code(
            code,
            on_stdout=lambda data: print(data, end=""),
            on_stderr=lambda data: print(f"[stderr] {data}", end=""),
            timeout=600,
        )
        print("=" * 40)

        if result.error:
            print(f"\n执行错误: {result.error.name}: {result.error.value}")
            print(result.error.traceback)

        return result
    finally:
        sandbox.kill()
        print("\n沙箱已销毁")


if __name__ == "__main__":
    # Step 1: 创建沙箱工具
    print("=" * 50)
    print("Step 1: 创建沙箱工具")
    print("=" * 50)

    if TENCENT_SECRET_ID == "你的SecretId":
        print("\n⚠️  请先配置腾讯云 SecretId/SecretKey!")
        print("   获取地址: https://console.cloud.tencent.com/cam/capi")
        print("\n   设置方式:")
        print("   export TENCENT_SECRET_ID=你的SecretId")
        print("   export TENCENT_SECRET_KEY=你的SecretKey")
        print("\n   或直接修改本脚本顶部的配置区")
        exit(1)

    success = create_sandbox_tool()
    if not success:
        print("沙箱工具创建失败，退出")
        exit(1)

    # Step 2: 执行代码
    print("\n" + "=" * 50)
    print("Step 2: 在沙箱中执行 Python 代码")
    print("=" * 50)

    python_code = """
import sys
import platform

print(f"Python 版本: {sys.version}")
print(f"平台: {platform.platform()}")
print("Hello from Tencent Agent Sandbox!")

# 示例计算
result = sum(range(1, 101))
print(f"1+2+...+100 = {result}")
"""

    run_code_in_sandbox(python_code)
