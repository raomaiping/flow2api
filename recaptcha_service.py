"""
reCAPTCHA Token 服务

保持浏览器持续运行，提供 HTTP API 来获取 reCAPTCHA token
这样可以避免每次请求都启动浏览器，大幅提升性能

使用方法:
    python recaptcha_service.py

API:
    POST /token
    {
        "project_id": "your-project-id"
    }
    
    返回:
    {
        "success": true,
        "token": "reCAPTCHA-token-string",
        "duration_ms": 1234
    }
"""
import asyncio
import sys
import io
from pathlib import Path
from typing import Optional, Dict
import time
from contextlib import asynccontextmanager

# 设置 UTF-8 编码（Windows 兼容）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
except ImportError:
    print("❌ Playwright 未安装")
    print("请运行: pip install playwright && playwright install chromium")
    sys.exit(1)

from src.core.logger import debug_logger
from src.core.config import config


# ========== 全局浏览器实例管理 ==========

class RecaptchaService:
    """reCAPTCHA Token 服务（复用浏览器实例）"""
    
    def __init__(self, headless: Optional[bool] = None):
        """初始化服务
        
        Args:
            headless: 是否使用无头模式
                     None: 自动检测（Docker环境默认True，本地默认False）
        """
        import os
        if headless is None:
            headless = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true" or \
                      os.path.exists("/.dockerenv") or \
                      os.getenv("CI") == "true"
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self._lock = asyncio.Lock()  # 用于并发控制
        self.website_key = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
        self._initialized = False
    
    async def initialize(self):
        """初始化浏览器（启动一次）"""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                debug_logger.log_info("[RecaptchaService] 正在启动浏览器...")
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox'
                    ]
                )
                self._initialized = True
                debug_logger.log_info(f"[RecaptchaService] ✅ 浏览器已启动 (headless={self.headless})")
            except Exception as e:
                debug_logger.log_error(f"[RecaptchaService] ❌ 浏览器启动失败: {str(e)}")
                raise
    
    async def get_token(self, project_id: str) -> Optional[str]:
        """获取 reCAPTCHA token（复用浏览器实例）
        
        Args:
            project_id: Flow项目ID
            
        Returns:
            reCAPTCHA token字符串，如果获取失败返回None
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        
        try:
            # 创建新的上下文（每次请求都创建新的上下文，类似新的浏览器会话）
            context: BrowserContext = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York'
            )
            page = await context.new_page()
            
            website_url = f"https://labs.google/fx/tools/flow/project/{project_id}"
            
            debug_logger.log_info(f"[RecaptchaService] 访问页面: {website_url}")
            
            # 访问页面
            try:
                await page.goto(website_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                debug_logger.log_warning(f"[RecaptchaService] 页面加载超时或失败: {str(e)}")
            
            # 检查并注入 reCAPTCHA v3 脚本（如果页面没有加载）
            debug_logger.log_info("[RecaptchaService] 检查并加载 reCAPTCHA v3 脚本...")
            script_loaded = await page.evaluate(f"""
                () => {{
                    if (window.grecaptcha && typeof window.grecaptcha.execute === 'function') {{
                        return true;
                    }}
                    return false;
                }}
            """)
            
            if not script_loaded:
                # 如果没有加载，注入脚本
                debug_logger.log_info("[RecaptchaService] 注入 reCAPTCHA v3 脚本...")
                await page.evaluate(f"""
                    () => {{
                        return new Promise((resolve) => {{
                            const script = document.createElement('script');
                            script.src = 'https://www.google.com/recaptcha/api.js?render={self.website_key}';
                            script.async = true;
                            script.defer = true;
                            script.onload = () => resolve(true);
                            script.onerror = () => resolve(false);
                            document.head.appendChild(script);
                        }});
                    }}
                """)
            
            # 等待reCAPTCHA加载和初始化
            debug_logger.log_info("[RecaptchaService] 等待reCAPTCHA初始化...")
            for i in range(20):  # 最多等待20秒
                grecaptcha_ready = await page.evaluate("""
                    () => {
                        return window.grecaptcha && 
                               typeof window.grecaptcha.execute === 'function';
                    }
                """)
                if grecaptcha_ready:
                    debug_logger.log_info(f"[RecaptchaService] reCAPTCHA 已准备好（等待了 {i*0.5} 秒）")
                    break
                await asyncio.sleep(0.5)
            else:
                debug_logger.log_warning("[RecaptchaService] reCAPTCHA 初始化超时，继续尝试执行...")
            
            # 额外等待一下确保完全初始化
            await page.wait_for_timeout(1000)
            
            # 执行reCAPTCHA并获取token
            debug_logger.log_info("[RecaptchaService] 执行reCAPTCHA验证...")
            token = await page.evaluate("""
                async (websiteKey) => {
                    try {
                        // 检查 grecaptcha 是否存在且有 execute 方法
                        if (!window.grecaptcha) {
                            console.error('[RecaptchaService] window.grecaptcha 不存在');
                            return null;
                        }
                        
                        if (typeof window.grecaptcha.execute !== 'function') {
                            console.error('[RecaptchaService] window.grecaptcha.execute 不是函数');
                            return null;
                        }
                        
                        // 确保grecaptcha已准备好
                        await new Promise((resolve, reject) => {
                            const timeout = setTimeout(() => {
                                reject(new Error('reCAPTCHA加载超时'));
                            }, 15000);
                            
                            if (window.grecaptcha && window.grecaptcha.ready) {
                                window.grecaptcha.ready(() => {
                                    clearTimeout(timeout);
                                    resolve();
                                });
                            } else {
                                clearTimeout(timeout);
                                resolve();
                            }
                        });
                        
                        // 执行reCAPTCHA v3
                        const token = await window.grecaptcha.execute(websiteKey, {
                            action: 'FLOW_GENERATION'
                        });
                        
                        return token;
                    } catch (error) {
                        console.error('[RecaptchaService] reCAPTCHA执行错误:', error);
                        return null;
                    }
                }
            """, self.website_key)
            
            # 关闭上下文（但保持浏览器运行）
            await context.close()
            
            duration_ms = (time.time() - start_time) * 1000
            
            if token:
                debug_logger.log_info(f"[RecaptchaService] ✅ Token获取成功（耗时 {duration_ms:.0f}ms）")
                return token
            else:
                debug_logger.log_error("[RecaptchaService] Token获取失败（返回null）")
                return None
                
        except Exception as e:
            debug_logger.log_error(f"[RecaptchaService] 获取token异常: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    async def close(self):
        """关闭浏览器和Playwright"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self._initialized = False
            debug_logger.log_info("[RecaptchaService] 浏览器已关闭")
        except Exception as e:
            debug_logger.log_error(f"[RecaptchaService] 关闭浏览器异常: {str(e)}")


# 全局服务实例
_recaptcha_service: Optional[RecaptchaService] = None


async def get_service() -> RecaptchaService:
    """获取全局服务实例"""
    global _recaptcha_service
    if _recaptcha_service is None:
        _recaptcha_service = RecaptchaService()
        await _recaptcha_service.initialize()
    return _recaptcha_service


# ========== FastAPI 应用 ==========

class TokenRequest(BaseModel):
    """Token 请求模型"""
    project_id: str


class TokenResponse(BaseModel):
    """Token 响应模型"""
    success: bool
    token: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化浏览器
    print("=" * 60)
    print("reCAPTCHA Token Service Starting...")
    print("=" * 60)
    service = await get_service()
    print("✅ 服务已就绪")
    print()
    
    yield
    
    # 关闭时清理资源
    print("=" * 60)
    print("reCAPTCHA Token Service Shutting down...")
    print("=" * 60)
    global _recaptcha_service
    if _recaptcha_service:
        await _recaptcha_service.close()
    print("✅ 服务已关闭")


app = FastAPI(
    title="reCAPTCHA Token Service",
    description="提供 reCAPTCHA v3 token 的 HTTP API 服务（复用浏览器实例）",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "reCAPTCHA Token Service",
        "version": "1.0.0",
        "endpoints": {
            "POST /token": "获取 reCAPTCHA token",
            "GET /health": "健康检查"
        }
    }


@app.get("/health")
async def health():
    """健康检查"""
    global _recaptcha_service
    if _recaptcha_service and _recaptcha_service._initialized:
        return {
            "status": "healthy",
            "browser_initialized": True,
            "headless": _recaptcha_service.headless
        }
    else:
        return {
            "status": "initializing",
            "browser_initialized": False
        }


@app.post("/token", response_model=TokenResponse)
async def get_token(request: TokenRequest):
    """获取 reCAPTCHA token
    
    请求体:
        {
            "project_id": "your-project-id"
        }
    
    响应:
        {
            "success": true,
            "token": "reCAPTCHA-token-string",
            "duration_ms": 1234.56
        }
    """
    start_time = time.time()
    
    try:
        service = await get_service()
        token = await service.get_token(request.project_id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        if token:
            return TokenResponse(
                success=True,
                token=token,
                duration_ms=duration_ms
            )
        else:
            return TokenResponse(
                success=False,
                error="Failed to get token",
                duration_ms=duration_ms
            )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error_msg = str(e)
        debug_logger.log_error(f"[API] 获取token异常: {error_msg}")
        return TokenResponse(
            success=False,
            error=error_msg,
            duration_ms=duration_ms
        )


def main():
    """主函数"""
    import os
    
    # 从环境变量获取端口，默认 8001（避免与主服务冲突）
    port = int(os.getenv("RECAPTCHA_SERVICE_PORT", "8001"))
    host = os.getenv("RECAPTCHA_SERVICE_HOST", "0.0.0.0")
    
    print(f"启动 reCAPTCHA Token Service...")
    print(f"监听地址: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    print()
    
    uvicorn.run(
        "recaptcha_service:app",
        host=host,
        port=port,
        log_level="info",
        reload=False  # 生产环境禁用自动重载
    )


if __name__ == "__main__":
    main()

