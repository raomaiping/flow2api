"""自实现的reCAPTCHA token获取器（不依赖第三方平台）"""
import asyncio
import os
from typing import Optional
from ..core.logger import debug_logger


class SelfRecaptchaSolver:
    """使用Playwright自实现reCAPTCHA token获取
    
    原理：
    1. 使用真实浏览器访问目标页面
    2. 等待reCAPTCHA v3自动执行
    3. 从页面中提取生成的token
    
    优点：
    - 完全免费（只需服务器资源）
    - 完全自主控制
    
    缺点：
    - 需要维护浏览器环境
    - 性能开销大（启动浏览器需要资源）
    - 可能被检测（需要反检测技术）
    """
    
    def __init__(self, headless: Optional[bool] = None):
        """
        Args:
            headless: 是否使用无头模式
                     None: 自动检测（Docker环境默认True，本地默认False）
                     True: 强制使用无头模式（适合Docker）
                     False: 强制使用有头模式（适合本地开发）
        """
        import os
        if headless is None:
            # 自动检测：如果在Docker中或CI环境中，使用无头模式
            headless = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true" or \
                      os.path.exists("/.dockerenv") or \
                      os.getenv("CI") == "true"
        self.headless = headless
        self.playwright = None
        self.browser = None
    
    async def _init_browser(self):
        """初始化浏览器（复用实例以提高性能）"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Playwright未安装。请运行: pip install playwright && playwright install chromium"
            )
        
        if self.playwright is None:
            self.playwright = await async_playwright().start()
            # Docker环境中强制使用无头模式
            launch_headless = self.headless if self.headless is not None else True
            self.browser = await self.playwright.chromium.launch(
                headless=launch_headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox'
                ]
            )
            debug_logger.log_info(f"[Self-reCAPTCHA] 浏览器已启动 (headless={self.headless})")
    
    async def get_recaptcha_token(self, project_id: str) -> Optional[str]:
        """获取reCAPTCHA token
        
        Args:
            project_id: Flow项目ID
            
        Returns:
            reCAPTCHA token字符串，如果获取失败返回None
        """
        try:
            await self._init_browser()
            
            # 创建新的上下文（类似新的浏览器会话）
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York'
            )
            page = await context.new_page()
            
            website_url = f"https://labs.google/fx/tools/flow/project/{project_id}"
            website_key = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
            
            debug_logger.log_info(f"[Self-reCAPTCHA] 访问页面: {website_url}")
            
            # 访问页面
            try:
                await page.goto(website_url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                debug_logger.log_warning(f"[Self-reCAPTCHA] 页面加载超时或失败: {str(e)}")
                # 继续尝试，即使加载不完全也可能已经加载了reCAPTCHA
            
            # 检查并注入 reCAPTCHA v3 脚本（如果页面没有加载）
            debug_logger.log_info("[Self-reCAPTCHA] 检查并加载 reCAPTCHA v3 脚本...")
            script_loaded = await page.evaluate(f"""
                () => {{
                    // 检查是否已经加载了 reCAPTCHA v3
                    if (window.grecaptcha && typeof window.grecaptcha.execute === 'function') {{
                        return true;
                    }}
                    return false;
                }}
            """)
            
            if not script_loaded:
                # 如果没有加载，注入脚本
                debug_logger.log_info("[Self-reCAPTCHA] 注入 reCAPTCHA v3 脚本...")
                await page.evaluate(f"""
                    () => {{
                        return new Promise((resolve) => {{
                            const script = document.createElement('script');
                            script.src = 'https://www.google.com/recaptcha/api.js?render={website_key}';
                            script.async = true;
                            script.defer = true;
                            script.onload = () => resolve(true);
                            script.onerror = () => resolve(false);
                            document.head.appendChild(script);
                        }});
                    }}
                """)
            
            # 等待reCAPTCHA加载和初始化
            debug_logger.log_info("[Self-reCAPTCHA] 等待reCAPTCHA初始化...")
            for i in range(20):  # 最多等待20秒
                grecaptcha_ready = await page.evaluate("""
                    () => {
                        return window.grecaptcha && 
                               typeof window.grecaptcha.execute === 'function';
                    }
                """)
                if grecaptcha_ready:
                    debug_logger.log_info(f"[Self-reCAPTCHA] reCAPTCHA 已准备好（等待了 {i*0.5} 秒）")
                    break
                await asyncio.sleep(0.5)
            else:
                debug_logger.log_warning("[Self-reCAPTCHA] reCAPTCHA 初始化超时，继续尝试执行...")
            
            # 额外等待一下确保完全初始化
            await page.wait_for_timeout(1000)
            
            # 执行reCAPTCHA并获取token
            debug_logger.log_info("[Self-reCAPTCHA] 执行reCAPTCHA验证...")
            token = await page.evaluate("""
                async (websiteKey) => {
                    try {
                        // 检查 grecaptcha 是否存在且有 execute 方法
                        if (!window.grecaptcha) {
                            console.error('[Self-reCAPTCHA] window.grecaptcha 不存在');
                            return null;
                        }
                        
                        if (typeof window.grecaptcha.execute !== 'function') {
                            console.error('[Self-reCAPTCHA] window.grecaptcha.execute 不是函数');
                            console.error('[Self-reCAPTCHA] grecaptcha 对象:', Object.keys(window.grecaptcha));
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
                                // 如果没有 ready 方法，直接 resolve
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
                        console.error('[Self-reCAPTCHA] reCAPTCHA执行错误:', error);
                        console.error('[Self-reCAPTCHA] 错误详情:', error.message, error.stack);
                        return null;
                    }
                }
            """, website_key)
            
            await context.close()
            
            if token:
                debug_logger.log_info("[Self-reCAPTCHA] ✅ Token获取成功")
                return token
            else:
                debug_logger.log_error("[Self-reCAPTCHA] Token获取失败（返回null）")
                return None
                
        except Exception as e:
            debug_logger.log_error(f"[Self-reCAPTCHA] 获取token异常: {str(e)}")
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
            debug_logger.log_info("[Self-reCAPTCHA] 浏览器已关闭")
        except Exception as e:
            debug_logger.log_error(f"[Self-reCAPTCHA] 关闭浏览器异常: {str(e)}")


# 全局实例（可选，用于复用浏览器）
_global_solver: Optional[SelfRecaptchaSolver] = None


async def get_global_solver(headless: bool = False) -> SelfRecaptchaSolver:
    """获取全局solver实例（复用浏览器）"""
    global _global_solver
    if _global_solver is None:
        _global_solver = SelfRecaptchaSolver(headless=headless)
    return _global_solver


async def close_global_solver():
    """关闭全局solver"""
    global _global_solver
    if _global_solver:
        await _global_solver.close()
        _global_solver = None

