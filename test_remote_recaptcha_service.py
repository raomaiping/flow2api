"""
测试远程部署的 reCAPTCHA Token 服务
"""
import asyncio
import sys
import io
import json
import httpx
from typing import Optional


def format_duration(ms: float) -> str:
    """将毫秒转换为易读的时间格式"""
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        seconds = ms / 1000
        return f"{seconds:.1f}秒 ({ms:.0f}ms)"
    else:
        minutes = ms / 60000
        seconds = (ms % 60000) / 1000
        return f"{minutes:.1f}分钟 {seconds:.0f}秒 ({ms:.0f}ms)"

# 设置 UTF-8 编码（Windows 兼容）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

SERVICE_URL = "http://127.0.0.1:8001"  # 默认本地地址，可以通过命令行参数覆盖


async def test_health():
    """测试健康检查"""
    print("=" * 60)
    print("测试健康检查")
    print("=" * 60)
    print()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            print(f"发送请求到: {SERVICE_URL}/health")
            response = await client.get(f"{SERVICE_URL}/health")
            
            print(f"状态码: {response.status_code}")
            print()
            
            data = response.json()
            print("响应:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print()
            
            if response.status_code == 200:
                print("=" * 60)
                print("✅ 健康检查通过")
                print("=" * 60)
                if data.get("browser_initialized"):
                    print("浏览器已初始化")
                else:
                    print("⚠️ 浏览器未初始化")
                return True
            else:
                print("=" * 60)
                print("❌ 健康检查失败")
                print("=" * 60)
                return False
    except Exception as e:
        print("=" * 60)
        print("❌ 健康检查异常")
        print("=" * 60)
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_get_token(project_id: str):
    """测试获取 token"""
    print()
    print("=" * 60)
    print("测试获取 Token")
    print("=" * 60)
    print()
    print(f"Project ID: {project_id}")
    print()
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            print("发送请求...")
            response = await client.post(
                f"{SERVICE_URL}/token",
                json={"project_id": project_id}
            )
            
            print(f"状态码: {response.status_code}")
            print()
            
            data = response.json()
            print("响应:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print()
            
            if response.status_code == 200:
                if data.get("success"):
                    token = data.get("token")
                    duration_ms = data.get("duration_ms", 0)
                    print("=" * 60)
                    print("✅ Token 获取成功！")
                    print("=" * 60)
                    print()
                    print(f"Token 长度: {len(token)} 字符")
                    print(f"耗时: {format_duration(duration_ms)}")
                    print()
                    print("Token 预览（前100字符）:")
                    print(token[:100] + "..." if len(token) > 100 else token)
                    return True
                else:
                    error = data.get("error", "Unknown error")
                    error_detail = data.get("error_detail")
                    duration_ms = data.get("duration_ms", 0)
                    print("=" * 60)
                    print("❌ Token 获取失败")
                    print("=" * 60)
                    print()
                    print(f"错误: {error}")
                    if error_detail:
                        print(f"详细错误: {error_detail}")
                    print(f"耗时: {format_duration(duration_ms)}")
                    return False
            else:
                print(f"❌ 请求失败: HTTP {response.status_code}")
                return False
    except httpx.ConnectError:
        print("=" * 60)
        print("❌ 连接失败")
        print("=" * 60)
        print("无法连接到服务，请检查URL是否正确")
        return False
    except httpx.TimeoutException:
        print("=" * 60)
        print("❌ 请求超时")
        print("=" * 60)
        print("服务响应时间过长（超过60秒）")
        return False
    except Exception as e:
        print("=" * 60)
        print("❌ 请求异常")
        print("=" * 60)
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_root():
    """测试根路径"""
    print("=" * 60)
    print("测试根路径")
    print("=" * 60)
    print()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            print(f"发送请求到: {SERVICE_URL}/")
            response = await client.get(f"{SERVICE_URL}/")
            
            print(f"状态码: {response.status_code}")
            print()
            
            data = response.json()
            print("响应:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print()
            
            if response.status_code == 200:
                print("✅ 根路径访问成功")
                return True
            else:
                print("❌ 根路径访问失败")
                return False
    except Exception as e:
        print(f"❌ 异常: {str(e)}")
        return False


async def main():
    """主函数"""
    global SERVICE_URL
    
    # 解析命令行参数
    # 用法: python test_remote_recaptcha_service.py [service_url] [project_id]
    # 如果只提供一个参数，它会被当作 project_id（使用默认的 SERVICE_URL）
    # 如果提供两个参数，第一个是 service_url，第二个是 project_id
    
    project_id = None
    
    if len(sys.argv) > 2:
        # 两个参数：service_url 和 project_id
        SERVICE_URL = sys.argv[1]
        project_id = sys.argv[2]
    elif len(sys.argv) > 1:
        # 一个参数：当作 project_id（使用默认的 SERVICE_URL）
        project_id = sys.argv[1]
    
    if SERVICE_URL.startswith("http"):
        if SERVICE_URL != "http://127.0.0.1:8001":
            print(f"🚀 开始测试远程 reCAPTCHA Token 服务")
        else:
            print(f"🚀 开始测试本地 reCAPTCHA Token 服务")
    print(f"📍 服务地址: {SERVICE_URL}")
    print()
    
    # 测试根路径
    await test_root()
    
    # 测试健康检查
    health_ok = await test_health()
    
    if not health_ok:
        print()
        print("⚠️ 健康检查失败，但继续测试token获取...")
        print()
    
    # 测试获取token
    if project_id:
        token_ok = await test_get_token(project_id)
        
        print()
        print("=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"健康检查: {'✅ 通过' if health_ok else '❌ 失败'}")
        print(f"Token 获取: {'✅ 成功' if token_ok else '❌ 失败'}")
        print()
    else:
        print("⚠️ 未提供 project_id，请输入一个有效的 project_id 进行测试")
        print("   用法: python test_remote_recaptcha_service.py [service_url] <project_id>")
        print()


if __name__ == "__main__":
    asyncio.run(main())

