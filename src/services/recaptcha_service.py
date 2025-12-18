"""
reCAPTCHA Token 服务（内部集成版本）

直接在主服务中使用，无需独立的 HTTP 服务
复用浏览器实例，提供高性能的 reCAPTCHA token 获取
"""
from __future__ import annotations

import asyncio
from typing import Optional, Dict, Tuple, TYPE_CHECKING
import time
import sys

if TYPE_CHECKING:
    from playwright.async_api import Route

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, Route
except ImportError:
    # Playwright 未安装时，会在使用时抛出错误
    Route = None  # 类型检查时使用

from ..core.logger import debug_logger


# ========== 常量配置 ==========

# 超时配置（毫秒）
TIMEOUT_PAGE_LOAD = 15000  # 页面加载超时
TIMEOUT_DOM_LOAD = 5000  # DOM加载超时
TIMEOUT_RECAPTCHA_READY = 10000  # reCAPTCHA准备超时
TIMEOUT_POLLING_INTERVAL = 0.3  # 轮询间隔（秒）
TIMEOUT_POLLING_MAX_ATTEMPTS = 15  # 最大轮询次数
TIMEOUT_EXECUTION_RETRY = 2000  # 执行重试超时
TIMEOUT_READY_CALLBACK = 8000  # grecaptcha.ready 回调超时

# 重试配置
MAX_EXECUTION_RETRIES = 2  # 最大执行重试次数
RETRY_WAIT_TIME = 1  # 重试等待时间（秒）

# 并发控制
MAX_CONCURRENT_REQUESTS = 5  # 最大并发请求数

# 浏览器配置
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--disable-setuid-sandbox'
]

# 默认浏览器上下文配置
DEFAULT_VIEWPORT = {'width': 1920, 'height': 1080}
DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
DEFAULT_LOCALE = 'en-US'
DEFAULT_TIMEZONE = 'America/New_York'

# reCAPTCHA配置
RECAPTCHA_WEBSITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
RECAPTCHA_ACTION = 'FLOW_GENERATION'
RECAPTCHA_SCRIPT_URL = f'https://www.google.com/recaptcha/api.js?render={RECAPTCHA_WEBSITE_KEY}'


class RecaptchaService:
    """reCAPTCHA Token 服务（复用浏览器实例）"""
    
    def __init__(self, headless: Optional[bool] = None):
        """初始化服务
        
        Args:
            headless: 是否使用无头模式
                     None: 强制使用无头模式（True）
        """
        # 强制使用无头模式
        if headless is None:
            headless = True
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self._lock = asyncio.Lock()  # 用于并发控制
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)  # 限制并发请求数量
        self.website_key = RECAPTCHA_WEBSITE_KEY
        self._initialized = False
        
        # 页面缓存：按 project_id 缓存页面，实现页面复用
        # 格式: {project_id: Page}
        self._page_cache: Dict[str, Page] = {}
        self._page_cache_lock = asyncio.Lock()  # 保护页面缓存的锁
        
        # 共享的浏览器上下文（所有页面共享）
        self._shared_context: Optional[BrowserContext] = None
    
    async def initialize(self):
        """初始化浏览器和共享上下文（启动一次）"""
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
                    args=BROWSER_ARGS
                )
                
                # 创建共享的浏览器上下文（所有页面共享）
                self._shared_context = await self.browser.new_context(
                    viewport=DEFAULT_VIEWPORT,
                    user_agent=DEFAULT_USER_AGENT,
                    locale=DEFAULT_LOCALE,
                    timezone_id=DEFAULT_TIMEZONE
                )
                
                # 在共享上下文中设置路由拦截（性能优化）
                await self._shared_context.route("**/*", self._route_handler)
                
                # 在共享上下文中注入 reCAPTCHA 脚本（提前加载）
                await self._shared_context.add_init_script(f"""
                    (function() {{
                        const script = document.createElement('script');
                        script.src = '{RECAPTCHA_SCRIPT_URL}';
                        script.async = true;
                        script.defer = true;
                        document.head.appendChild(script);
                    }})();
                """)
                
                self._initialized = True
                debug_logger.log_info(f"[RecaptchaService] ✅ 浏览器已启动 (headless={self.headless})")
                debug_logger.log_info("[RecaptchaService] ✅ 共享浏览器上下文已创建")
            except Exception as e:
                debug_logger.log_error(f"[RecaptchaService] ❌ 浏览器启动失败: {str(e)}")
                raise
    
    async def _route_handler(self, route: "Route") -> None:
        """路由处理器：拦截并阻止不必要的资源加载"""
        request = route.request
        resource_type = request.resource_type
        url = request.url.lower()
        
        # 允许的资源类型
        allowed_types = {"document", "script", "xhr", "fetch", "websocket"}
        
        # 优先检查：允许所有 reCAPTCHA 和 Google 相关请求（必须）
        google_domains = [
            "recaptcha",
            "google.com",
            "googleapis.com",
            "gstatic.com",
            "googleusercontent.com",
            "google-analytics.com"
        ]
        
        if any(domain in url for domain in google_domains):
            await route.continue_()
            return
        
        # 允许主文档和脚本（必须）
        if resource_type in allowed_types:
            await route.continue_()
            return
        
        # 阻止不必要的资源（图片、CSS、字体、媒体等）
        if resource_type in {"image", "stylesheet", "font", "media"}:
            await route.abort()
            return
        
        # 对于其他类型，如果 URL 包含关键域名则允许，否则阻止
        if resource_type == "other":
            if any(domain in url for domain in ["google", "labs.google"]):
                await route.continue_()
            else:
                await route.abort()
            return
        
        # 默认继续（安全起见）
        await route.continue_()
    
    async def _wait_for_page_stable(self, page: Page, timeout: int = TIMEOUT_DOM_LOAD) -> None:
        """等待页面稳定"""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception as e:
            debug_logger.log_warning(f"[RecaptchaService] 等待页面稳定超时: {str(e)}")
    
    async def _check_grecaptcha_loaded(self, page: Page) -> bool:
        """检查 reCAPTCHA 是否已加载"""
        try:
            return await page.evaluate("""
                () => {
                    return window.grecaptcha && 
                           typeof window.grecaptcha.execute === 'function';
                }
            """)
        except Exception as e:
            if "Execution context was destroyed" in str(e):
                debug_logger.log_warning("[RecaptchaService] 检查脚本时发生导航，等待页面稳定...")
                await self._wait_for_page_stable(page)
                try:
                    return await page.evaluate("""
                        () => {
                            return window.grecaptcha && 
                                   typeof window.grecaptcha.execute === 'function';
                        }
                    """)
                except Exception as e2:
                    debug_logger.log_error(f"[RecaptchaService] 重试检查脚本失败: {str(e2)}")
                    return False
            else:
                debug_logger.log_warning(f"[RecaptchaService] 检查脚本错误: {str(e)}")
                return False
    
    async def _inject_recaptcha_script(self, page: Page) -> bool:
        """注入 reCAPTCHA v3 脚本（备用方案）"""
        debug_logger.log_info("[RecaptchaService] 检查并注入 reCAPTCHA v3 脚本（备用方案）...")
        try:
            script_exists = await page.evaluate("""
                () => {
                    return !!document.querySelector('script[src*="recaptcha/api.js"]');
                }
            """)
            
            if script_exists:
                debug_logger.log_info("[RecaptchaService] reCAPTCHA 脚本已存在，跳过注入")
                return True
            
            script_injected = await page.evaluate(f"""
                () => {{
                    return new Promise((resolve) => {{
                        const script = document.createElement('script');
                        script.src = '{RECAPTCHA_SCRIPT_URL}';
                        script.async = true;
                        script.defer = true;
                        script.onload = () => resolve(true);
                        script.onerror = () => resolve(false);
                        document.head.appendChild(script);
                    }});
                }}
            """)
            if not script_injected:
                debug_logger.log_warning("[RecaptchaService] reCAPTCHA 脚本注入可能失败")
            return script_injected
        except Exception as e:
            debug_logger.log_warning(f"[RecaptchaService] 脚本注入时发生导航: {str(e)}")
            await self._wait_for_page_stable(page)
            return False
    
    async def _wait_for_recaptcha_ready(self, page: Page) -> bool:
        """等待 reCAPTCHA 初始化完成"""
        debug_logger.log_info("[RecaptchaService] 等待reCAPTCHA初始化...")
        
        try:
            await page.wait_for_function(
                """() => {
                    return window.grecaptcha && 
                           typeof window.grecaptcha.execute === 'function';
                }""",
                timeout=TIMEOUT_RECAPTCHA_READY
            )
            debug_logger.log_info("[RecaptchaService] reCAPTCHA 已准备好")
            return True
        except Exception as e:
            debug_logger.log_warning(f"[RecaptchaService] wait_for_function 超时: {str(e)}，使用轮询作为后备...")
        
        for i in range(TIMEOUT_POLLING_MAX_ATTEMPTS):
            try:
                grecaptcha_ready = await page.evaluate("""
                    () => {
                        return window.grecaptcha && 
                               typeof window.grecaptcha.execute === 'function';
                    }
                """)
                if grecaptcha_ready:
                    debug_logger.log_info(
                        f"[RecaptchaService] reCAPTCHA 已准备好（轮询，等待了 {i * TIMEOUT_POLLING_INTERVAL:.1f} 秒）"
                    )
                    return True
            except Exception as eval_error:
                if "Execution context was destroyed" in str(eval_error):
                    debug_logger.log_warning("[RecaptchaService] 轮询时发生导航，等待页面稳定...")
                    await self._wait_for_page_stable(page)
                else:
                    debug_logger.log_warning(f"[RecaptchaService] 轮询检查错误: {str(eval_error)}")
            
            await asyncio.sleep(TIMEOUT_POLLING_INTERVAL)
        
        debug_logger.log_warning("[RecaptchaService] reCAPTCHA初始化超时，继续尝试执行...")
        return False
    
    async def _execute_recaptcha(self, page: Page) -> Dict:
        """执行 reCAPTCHA 验证"""
        await self._wait_for_page_stable(page, timeout=2000)
        
        for retry in range(MAX_EXECUTION_RETRIES):
            try:
                token = await page.evaluate(f"""
                    async (websiteKey) => {{
                        try {{
                            return await new Promise((resolve) => {{
                                let resolved = false;
                                
                                const executeRecaptcha = () => {{
                                    if (resolved) return;
                                    
                                    if (!window.grecaptcha) {{
                                        resolved = true;
                                        resolve({{error: 'window.grecaptcha 不存在'}});
                                        return;
                                    }}
                                    
                                    if (typeof window.grecaptcha.execute !== 'function') {{
                                        resolved = true;
                                        resolve({{error: 'window.grecaptcha.execute 不是函数'}});
                                        return;
                                    }}
                                    
                                    window.grecaptcha.execute(websiteKey, {{
                                        action: '{RECAPTCHA_ACTION}'
                                    }}).then(token => {{
                                        if (!resolved) {{
                                            resolved = true;
                                            resolve({{token: token}});
                                        }}
                                    }}).catch(error => {{
                                        if (!resolved) {{
                                            resolved = true;
                                            resolve({{error: error.message || String(error)}});
                                        }}
                                    }});
                                }};
                                
                                const timeoutId = setTimeout(() => {{
                                    if (!resolved) {{
                                        resolved = true;
                                        resolve({{error: 'grecaptcha.ready 超时（{TIMEOUT_READY_CALLBACK}ms），grecaptcha 状态: ' + 
                                            (window.grecaptcha ? '存在' : '不存在') + 
                                            (window.grecaptcha && typeof window.grecaptcha.execute === 'function' ? '，execute可用' : '，execute不可用')}});
                                    }}
                                }}, {TIMEOUT_READY_CALLBACK});
                                
                                if (window.grecaptcha && typeof window.grecaptcha.execute === 'function') {{
                                    clearTimeout(timeoutId);
                                    executeRecaptcha();
                                    return;
                                }}
                                
                                if (window.grecaptcha && window.grecaptcha.ready && typeof window.grecaptcha.ready === 'function') {{
                                    window.grecaptcha.ready(() => {{
                                        clearTimeout(timeoutId);
                                        executeRecaptcha();
                                    }});
                                }} else {{
                                    const checkInterval = setInterval(() => {{
                                        if (resolved) {{
                                            clearInterval(checkInterval);
                                            return;
                                        }}
                                        
                                        if (window.grecaptcha) {{
                                            if (typeof window.grecaptcha.execute === 'function') {{
                                                clearInterval(checkInterval);
                                                clearTimeout(timeoutId);
                                                executeRecaptcha();
                                            }} else if (window.grecaptcha.ready && typeof window.grecaptcha.ready === 'function') {{
                                                clearInterval(checkInterval);
                                                window.grecaptcha.ready(() => {{
                                                    clearTimeout(timeoutId);
                                                    executeRecaptcha();
                                                }});
                                            }}
                                        }}
                                    }}, 200);
                                    
                                    setTimeout(() => {{
                                        clearInterval(checkInterval);
                                    }}, {TIMEOUT_READY_CALLBACK});
                                }}
                            }});
                        }} catch (error) {{
                            return {{error: error.message || String(error)}};
                        }}
                    }}
                """, self.website_key)
                return token
            except Exception as eval_error:
                if "Execution context was destroyed" in str(eval_error) and retry < MAX_EXECUTION_RETRIES - 1:
                    debug_logger.log_warning(
                        f"[RecaptchaService] 执行时发生导航（重试 {retry + 1}/{MAX_EXECUTION_RETRIES}）: {str(eval_error)}"
                    )
                    await self._wait_for_page_stable(page)
                    await asyncio.sleep(RETRY_WAIT_TIME)
                else:
                    debug_logger.log_error(f"[RecaptchaService] 执行reCAPTCHA验证失败: {str(eval_error)}")
                    return {"error": f"Execution error: {str(eval_error)}"}
        
        return {"error": "执行失败：达到最大重试次数"}
    
    async def _load_page(self, page: Page, url: str) -> None:
        """加载页面并等待稳定"""
        try:
            await page.goto(url, wait_until="commit", timeout=TIMEOUT_PAGE_LOAD)
            await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_DOM_LOAD)
        except Exception as e:
            debug_logger.log_warning(f"[RecaptchaService] 页面加载超时或失败: {str(e)}")
            await self._wait_for_page_stable(page)
    
    async def _ensure_recaptcha_loaded(self, page: Page) -> None:
        """确保 reCAPTCHA 脚本已加载"""
        debug_logger.log_info("[RecaptchaService] 检查并加载 reCAPTCHA v3 脚本...")
        
        script_loaded = await self._check_grecaptcha_loaded(page)
        
        if not script_loaded:
            await self._inject_recaptcha_script(page)
        
        await self._wait_for_recaptcha_ready(page)
    
    def _process_token_result(self, token: Dict, duration_ms: float) -> tuple[Optional[str], Optional[str]]:
        """处理 token 结果"""
        if isinstance(token, dict):
            if 'token' in token and token['token']:
                debug_logger.log_info(f"[RecaptchaService] ✅ Token获取成功（耗时 {duration_ms:.0f}ms）")
                return token['token'], None
            else:
                error_msg = token.get('error', 'Unknown error')
                error_detail = f"reCAPTCHA执行失败: {error_msg}"
                debug_logger.log_error(f"[RecaptchaService] Token获取失败: {error_detail}，耗时 {duration_ms:.0f}ms")
                return None, error_detail
        else:
            if token:
                debug_logger.log_info(f"[RecaptchaService] ✅ Token获取成功（耗时 {duration_ms:.0f}ms）")
                return token, None
            else:
                error_detail = "Token获取失败，可能原因：reCAPTCHA脚本未加载、页面加载超时、或网络问题"
                debug_logger.log_error(f"[RecaptchaService] Token获取失败（返回null），耗时 {duration_ms:.0f}ms")
                return None, error_detail
    
    async def _cleanup_invalid_pages(self) -> None:
        """清理无效的页面缓存"""
        async with self._page_cache_lock:
            invalid_project_ids = []
            for project_id, page in self._page_cache.items():
                try:
                    _ = page.url
                except Exception:
                    invalid_project_ids.append(project_id)
            
            for project_id in invalid_project_ids:
                del self._page_cache[project_id]
                debug_logger.log_info(f"[RecaptchaService] 清理无效页面缓存 (project_id: {project_id})")
    
    async def _get_or_create_page(self, project_id: str) -> Page:
        """获取或创建页面（页面复用优化）"""
        if len(self._page_cache) > 0 and len(self._page_cache) % 10 == 0:
            await self._cleanup_invalid_pages()
        
        async with self._page_cache_lock:
            if project_id in self._page_cache:
                page = self._page_cache[project_id]
                try:
                    _ = page.url
                    debug_logger.log_info(f"[RecaptchaService] ✅ 复用已存在的页面 (project_id: {project_id[:20]}...)")
                    return page
                except Exception:
                    debug_logger.log_warning(f"[RecaptchaService] ⚠️ 缓存的页面已关闭，创建新页面 (project_id: {project_id[:20]}...)")
                    del self._page_cache[project_id]
            
            debug_logger.log_info(f"[RecaptchaService] 🆕 创建新页面 (project_id: {project_id[:20]}...，当前缓存页面数: {len(self._page_cache)})")
            page = await self._shared_context.new_page()
            self._page_cache[project_id] = page
            return page
    
    async def get_token(self, project_id: str) -> Tuple[Optional[str], Optional[str]]:
        """获取 reCAPTCHA token（复用浏览器实例和页面）
        
        Args:
            project_id: Flow项目ID
            
        Returns:
            (reCAPTCHA token字符串, 错误信息)，如果获取失败返回 (None, 错误信息)
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._semaphore:
            start_time = time.time()
            page: Optional[Page] = None
            
            try:
                page = await self._get_or_create_page(project_id)
                
                website_url = f"https://labs.google/fx/tools/flow/project/{project_id}"
                
                try:
                    current_url = page.url
                    is_same_url = current_url == website_url or website_url in current_url
                    
                    if is_same_url:
                        debug_logger.log_info(f"[RecaptchaService] 刷新页面: {website_url}")
                        try:
                            await page.reload(wait_until="commit", timeout=TIMEOUT_PAGE_LOAD)
                            await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_DOM_LOAD)
                        except Exception as e:
                            debug_logger.log_warning(f"[RecaptchaService] 页面刷新失败，尝试重新加载: {str(e)}")
                            await self._load_page(page, website_url)
                    else:
                        debug_logger.log_info(f"[RecaptchaService] 加载新页面: {website_url}")
                        await self._load_page(page, website_url)
                except Exception:
                    debug_logger.log_info(f"[RecaptchaService] 首次加载页面: {website_url}")
                    await self._load_page(page, website_url)
                
                await self._ensure_recaptcha_loaded(page)
                
                debug_logger.log_info("[RecaptchaService] 执行reCAPTCHA验证...")
                token = await self._execute_recaptcha(page)
                
                duration_ms = (time.time() - start_time) * 1000
                
                return self._process_token_result(token, duration_ms)
                    
            except Exception as e:
                error_detail = f"获取token异常: {str(e)}"
                debug_logger.log_error(f"[RecaptchaService] {error_detail}")
                import traceback
                debug_logger.log_error(f"[RecaptchaService] 异常堆栈: {traceback.format_exc()}")
                return None, error_detail
    
    async def close(self):
        """关闭浏览器和Playwright"""
        try:
            async with self._page_cache_lock:
                for project_id, page in list(self._page_cache.items()):
                    try:
                        await page.close()
                        debug_logger.log_info(f"[RecaptchaService] 已关闭页面 (project_id: {project_id})")
                    except Exception as e:
                        debug_logger.log_warning(f"[RecaptchaService] 关闭页面失败 (project_id: {project_id}): {str(e)}")
                self._page_cache.clear()
            
            if self._shared_context:
                try:
                    await self._shared_context.close()
                    self._shared_context = None
                    debug_logger.log_info("[RecaptchaService] 共享上下文已关闭")
                except Exception as e:
                    debug_logger.log_warning(f"[RecaptchaService] 关闭共享上下文失败: {str(e)}")
            
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


async def get_recaptcha_service() -> Optional[RecaptchaService]:
    """获取全局 reCAPTCHA 服务实例"""
    global _recaptcha_service
    
    # 首先检查 Playwright 是否可用
    try:
        from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, Route
    except ImportError:
        debug_logger.log_warning("[RecaptchaService] Playwright 未安装，无法使用 reCAPTCHA 服务")
        debug_logger.log_info("[RecaptchaService] 请运行: pip install playwright && playwright install chromium")
        return None
    
    if _recaptcha_service is None:
        try:
            debug_logger.log_info("[RecaptchaService] 正在初始化 reCAPTCHA 服务...")
            _recaptcha_service = RecaptchaService()
            await _recaptcha_service.initialize()
            debug_logger.log_info("[RecaptchaService] ✅ reCAPTCHA 服务初始化成功")
        except Exception as e:
            debug_logger.log_error(f"[RecaptchaService] ❌ 初始化失败: {str(e)}")
            import traceback
            debug_logger.log_error(f"[RecaptchaService] 初始化异常详情: {traceback.format_exc()}")
            _recaptcha_service = None
            return None
    
    # 确保服务已初始化
    if not _recaptcha_service._initialized:
        try:
            debug_logger.log_info("[RecaptchaService] 服务未初始化，正在初始化...")
            await _recaptcha_service.initialize()
        except Exception as e:
            debug_logger.log_error(f"[RecaptchaService] ❌ 初始化失败: {str(e)}")
            return None
    
    return _recaptcha_service


async def close_recaptcha_service():
    """关闭全局 reCAPTCHA 服务实例"""
    global _recaptcha_service
    if _recaptcha_service:
        await _recaptcha_service.close()
        _recaptcha_service = None
