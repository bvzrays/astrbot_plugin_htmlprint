#!/usr/bin/env python3
"""
HTML Print Plugin for AstrBot
通过指令 /html <网址> 提取网页HTML内容并以文件形式发送
"""

import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
import re
import urllib.parse
from bs4 import BeautifulSoup
from pathlib import Path
import base64

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

@register("htmlprint", "bvzrays", "HTML网页内容提取插件", "1.0.0", "https://github.com/your-repo/astrbot-plugin-htmlprint")
class HTMLPrintPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.context = context
        self.config: AstrBotConfig | None = config
        
        # 获取插件目录
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        # 在插件目录下创建保存目录
        self.save_dir = os.path.join(self.plugin_dir, 'html_files')
        os.makedirs(self.save_dir, exist_ok=True)
        logger.info(f"HTMLPrint插件初始化完成，保存目录: {self.save_dir}")
        
        # 启动清理任务
        self.cleanup_task = asyncio.create_task(self.cleanup_old_files())
    
    @filter.command("html")
    async def html_command(self, event: AstrMessageEvent, url: str):
        """提取网页HTML内容并以文件形式发送"""
        try:
            # 检查插件是否启用
            if self.config and not self.config.get("enabled", True):
                yield event.plain_result("HTML内容提取插件已禁用")
                return
            
            # 验证URL格式
            if not self.is_valid_url(url):
                yield event.plain_result("请输入有效的URL地址，例如: https://www.example.com")
                return
            
            # 添加协议前缀（如果没有的话）
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            yield event.plain_result(f"正在获取 {url} 的HTML内容和图片，请稍候...")
            
            # 获取HTML内容
            html_content = await self.fetch_html(url)
            if not html_content:
                yield event.plain_result("无法获取网页内容，请检查URL是否正确或稍后再试。")
                return
            
            # 检测是否为空白页面（可能是JavaScript动态加载）
            if self.is_likely_empty_page(html_content):
                logger.info(f"检测到可能是JavaScript动态加载的页面，尝试使用浏览器渲染: {url}")
                yield event.plain_result("检测到页面可能需要JavaScript渲染，正在使用浏览器加载...")
                browser_html = await self.fetch_html_with_browser(url)
                if browser_html and len(browser_html) > len(html_content) * 1.5:
                    # 如果浏览器渲染的内容明显更多，使用浏览器渲染的结果
                    html_content = browser_html
                    logger.info(f"使用浏览器渲染的HTML，内容长度: {len(html_content)}")
                elif browser_html:
                    html_content = browser_html
            
            # 解析HTML并下载图片
            base_url = url
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 在插件目录下创建页面目录
            page_dir = os.path.join(self.save_dir, f'page_{timestamp}')
            os.makedirs(page_dir, exist_ok=True)
            
            html_with_resources, images = await self.download_resources_and_update_html(html_content, base_url, page_dir)
            
            # 发送图片到聊天（使用Node转发消息形式）
            if images:
                yield event.plain_result(f"找到 {len(images)} 张图片，正在发送...")
                
                # 创建转发消息内容
                contents = []
                for idx, (img_path, img_url) in enumerate(images):
                    try:
                        # 添加图片描述
                        contents.append(Comp.Plain(f"图片 {idx + 1}/{len(images)}\n"))
                        # 添加图片
                        contents.append(Comp.Image.fromFileSystem(img_path))
                        contents.append(Comp.Plain("\n"))
                    except Exception as e:
                        logger.warning(f"添加图片到转发消息失败 {img_path}: {e}")
                        # 如果本地文件失败，尝试使用URL
                        try:
                            contents.append(Comp.Plain(f"图片 {idx + 1}/{len(images)} (URL)\n"))
                            contents.append(Comp.Image.fromURL(img_url))
                            contents.append(Comp.Plain("\n"))
                        except Exception as e2:
                            logger.warning(f"使用URL添加图片也失败 {img_url}: {e2}")
                
                if contents:
                    try:
                        # 获取机器人ID用于显示
                        try:
                            uin = int(event.get_self_id()) if event.get_self_id() and event.get_self_id().isdigit() else 0
                        except Exception:
                            uin = 0
                        node = Comp.Node(uin=uin, name="网页图片", content=contents)
                        yield event.chain_result([node])
                    except Exception as e:
                        logger.error(f"发送转发消息失败: {e}")
                        # 如果转发消息失败，回退到单独发送
                        for img_path, img_url in images:
                            try:
                                yield event.image_result(img_path)
                            except Exception as e2:
                                logger.warning(f"发送图片失败 {img_path}: {e2}")
            
            # 保存HTML到临时文件（所有资源已嵌入base64，不需要外部文件）
            file_path = await self.save_html_to_file(html_with_resources, url, page_dir)
            
            # 发送HTML文件
            filename = f"网页_{self.extract_domain(url)}.html"
            yield event.chain_result([Comp.File(file=file_path, name=filename)])
            
            # 设置5分钟后删除整个页面目录（给用户更多时间查看）
            asyncio.create_task(self.delete_dir_later(page_dir, 300))
            
        except Exception as e:
            logger.error(f"处理HTML指令时出错: {e}", exc_info=True)
            yield event.plain_result(f"处理过程中出现错误: {str(e)}")
    
    def is_likely_empty_page(self, html_content: str) -> bool:
        """
        检测HTML页面是否可能是空白的（需要JavaScript渲染）
        """
        if not html_content:
            return True
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 移除script和style标签后检查文本内容
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        text = soup.get_text()
        # 清理空白字符
        text = ' '.join(text.split())
        
        # 如果文本内容很少（少于100个字符），可能是空白页面
        if len(text) < 100:
            return True
        
        # 检查是否有明显的JavaScript框架标记
        body = soup.find('body')
        if body:
            body_text = body.get_text()
            body_text = ' '.join(body_text.split())
            # 如果body中文本很少，可能是动态加载
            if len(body_text) < 50:
                return True
        
        # 检查是否有大量的script标签（可能是SPA应用）
        scripts = soup.find_all('script')
        if len(scripts) > 5:
            # 如果有很多script但文本内容少，可能是SPA
            if len(text) < 200:
                return True
        
        return False
    
    async def fetch_html_with_browser(self, url: str) -> str:
        """
        使用Playwright浏览器渲染JavaScript并获取HTML内容
        """
        try:
            from playwright.async_api import async_playwright
            
            playwright = None
            browser = None
            
            try:
                logger.info(f"启动Playwright浏览器渲染: {url}")
                playwright = await async_playwright().start()
                
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security'
                    ]
                )
                
                page = await browser.new_page()
                
                # 设置用户代理
                await page.set_extra_http_headers({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })
                
                # 设置视口大小
                await page.set_viewport_size({"width": 1920, "height": 1080})
                
                # 访问页面并等待加载
                logger.info(f"浏览器访问页面: {url}")
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # 等待额外时间让JavaScript执行
                await page.wait_for_timeout(2000)
                
                # 获取渲染后的HTML
                html_content = await page.content()
                
                logger.info(f"浏览器渲染完成，HTML长度: {len(html_content)}")
                
                return html_content
                
            except Exception as e:
                logger.error(f"浏览器渲染失败: {e}", exc_info=True)
                return None
            finally:
                # 清理资源
                if browser:
                    try:
                        await browser.close()
                    except:
                        pass
                if playwright:
                    try:
                        await playwright.stop()
                    except:
                        pass
                        
        except ImportError:
            logger.warning("Playwright未安装，无法使用浏览器渲染。请运行: pip install playwright && playwright install chromium")
            return None
        except Exception as e:
            logger.error(f"使用浏览器渲染时出错: {e}", exc_info=True)
            return None
    
    async def fetch_html(self, url: str) -> str:
        """
        异步获取网页HTML内容
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'text/html' in content_type or 'text/plain' in content_type:
                            return await response.text()
                        else:
                            # 尝试以文本形式获取
                            return await response.text()
                    else:
                        logger.warning(f"获取网页失败，状态码: {response.status}, URL: {url}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"获取网页超时: {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"网络请求错误: {e}, URL: {url}")
            return None
        except Exception as e:
            logger.error(f"获取网页内容时出错: {e}, URL: {url}", exc_info=True)
            return None
    
    async def download_resources_and_update_html(self, html_content: str, base_url: str, page_dir: str):
        """
        解析HTML，下载所有资源（图片、CSS、JS），将资源转换为base64嵌入HTML，并保存图片文件
        返回: (更新后的HTML内容（所有资源已嵌入base64）, [(本地图片路径, 原始URL), ...])
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # 在页面目录中创建images子目录（用于保存原图文件）
            images_dir = os.path.join(page_dir, 'images')
            os.makedirs(images_dir, exist_ok=True)
            
            downloaded_images = []
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': base_url
            }
            
            async with aiohttp.ClientSession() as session:
                # 1. 处理所有图片
                img_tags = soup.find_all('img')
                for idx, img in enumerate(img_tags):
                    img_url = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                    if not img_url:
                        continue
                    
                    # 处理相对URL
                    img_url = urllib.parse.urljoin(base_url, img_url)
                    
                    try:
                        async with session.get(img_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status == 200:
                                content = await response.read()
                                content_type = response.headers.get('Content-Type', 'image/jpeg')
                                
                                # 获取MIME类型
                                mime_type = 'image/jpeg'
                                ext = '.jpg'
                                if 'png' in content_type:
                                    ext = '.png'
                                    mime_type = 'image/png'
                                elif 'gif' in content_type:
                                    ext = '.gif'
                                    mime_type = 'image/gif'
                                elif 'webp' in content_type:
                                    ext = '.webp'
                                    mime_type = 'image/webp'
                                else:
                                    parsed = urllib.parse.urlparse(img_url)
                                    path_ext = os.path.splitext(parsed.path)[1]
                                    if path_ext:
                                        ext = path_ext
                                        if ext.lower() == '.png':
                                            mime_type = 'image/png'
                                        elif ext.lower() == '.gif':
                                            mime_type = 'image/gif'
                                        elif ext.lower() == '.webp':
                                            mime_type = 'image/webp'
                                
                                # 保存图片到本地文件（用于聊天发送）
                                img_filename = f"img_{idx}{ext}"
                                img_path = os.path.join(images_dir, img_filename)
                                with open(img_path, 'wb') as f:
                                    f.write(content)
                                
                                # 将图片转换为base64并嵌入HTML
                                img_base64 = base64.b64encode(content).decode('utf-8')
                                data_uri = f"data:{mime_type};base64,{img_base64}"
                                img['src'] = data_uri
                                
                                downloaded_images.append((img_path, img_url))
                                logger.info(f"已下载并嵌入图片: {img_url}")
                    except Exception as e:
                        logger.warning(f"下载图片失败 {img_url}: {e}")
                        continue
                
                # 2. 处理所有外部CSS样式表
                link_tags = soup.find_all('link', rel='stylesheet')
                for link in link_tags:
                    css_url = link.get('href')
                    if not css_url:
                        continue
                    
                    # 处理相对URL
                    css_url = urllib.parse.urljoin(base_url, css_url)
                    
                    try:
                        async with session.get(css_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status == 200:
                                css_content = await response.text()
                                
                                # 确保CSS内容不为空
                                if not css_content:
                                    logger.warning(f"CSS内容为空: {css_url}")
                                    continue
                                
                                # 处理CSS中的相对URL（如背景图片、字体等）
                                try:
                                    css_content = await self.process_css_urls(css_content, css_url, session, headers)
                                    # 确保处理后的内容仍然是字符串
                                    if not isinstance(css_content, str):
                                        logger.warning(f"CSS处理结果不是字符串: {css_url}")
                                        css_content = str(css_content) if css_content is not None else ""
                                except Exception as e:
                                    logger.warning(f"处理CSS URLs时出错 {css_url}: {e}，使用原始CSS")
                                    # 如果处理失败，使用原始CSS内容
                                
                                # 创建内联style标签替换link标签
                                if css_content:
                                    style_tag = soup.new_tag('style')
                                    style_tag.string = css_content
                                    link.replace_with(style_tag)
                                    logger.info(f"已下载并嵌入CSS: {css_url}")
                                else:
                                    logger.warning(f"CSS内容为空，跳过: {css_url}")
                    except Exception as e:
                        logger.warning(f"下载CSS失败 {css_url}: {e}")
                        continue
                
                # 3. 处理所有外部JavaScript文件
                script_tags = soup.find_all('script', src=True)
                for script in script_tags:
                    js_url = script.get('src')
                    if not js_url:
                        continue
                    
                    # 跳过data:和javascript:协议
                    if js_url.startswith(('data:', 'javascript:')):
                        continue
                    
                    # 处理相对URL
                    js_url = urllib.parse.urljoin(base_url, js_url)
                    
                    try:
                        async with session.get(js_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status == 200:
                                js_content = await response.text()
                                
                                # 创建内联script标签替换外部script标签
                                new_script = soup.new_tag('script')
                                new_script.string = js_content
                                # 保留原有属性（如type、async等）
                                for attr, value in script.attrs.items():
                                    if attr != 'src':
                                        new_script[attr] = value
                                script.replace_with(new_script)
                                
                                logger.info(f"已下载并嵌入JS: {js_url}")
                    except Exception as e:
                        logger.warning(f"下载JS失败 {js_url}: {e}")
                        continue
            
            # 返回更新后的HTML（所有资源已嵌入）和下载的图片列表
            return str(soup), downloaded_images
            
        except Exception as e:
            logger.error(f"处理资源时出错: {e}", exc_info=True)
            return html_content, []
    
    async def process_css_urls(self, css_content: str, css_url: str, session: aiohttp.ClientSession, headers: dict):
        """
        处理CSS中的相对URL（如背景图片、字体等），转换为base64
        """
        import re
        
        # 匹配CSS中的url()引用
        url_pattern = re.compile(r'url\s*\(\s*["\']?([^"\'()]+)["\']?\s*\)', re.IGNORECASE)
        
        async def replace_url(match):
            try:
                url = match.group(1)
                if not url:
                    return match.group(0)
                
                # 跳过data:和绝对URL（http/https）
                if url.startswith(('data:', 'http://', 'https://')):
                    return match.group(0)
                
                # 处理相对URL
                full_url = urllib.parse.urljoin(css_url, url)
                
                try:
                    async with session.get(full_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 200:
                            content = await response.read()
                            content_type = response.headers.get('Content-Type', 'application/octet-stream')
                            
                            # 转换为base64
                            content_base64 = base64.b64encode(content).decode('utf-8')
                            return f"url(data:{content_type};base64,{content_base64})"
                except Exception as e:
                    logger.warning(f"处理CSS中的URL失败 {full_url}: {e}")
                    return match.group(0)  # 保留原始URL
            except Exception as e:
                logger.warning(f"处理CSS URL匹配时出错: {e}")
                return match.group(0)  # 确保总是返回字符串
        
        # 找到所有匹配的URL
        matches = list(url_pattern.finditer(css_content))
        if not matches:
            return css_content
        
        # 异步处理所有URL
        try:
            replacements = await asyncio.gather(*[replace_url(match) for match in matches])
            
            # 确保所有替换值都是字符串
            replacements = [str(r) if r is not None else match.group(0) for r, match in zip(replacements, matches)]
            
            # 重新构建CSS内容
            last_pos = 0
            new_css = []
            for i, match in enumerate(matches):
                new_css.append(css_content[last_pos:match.start()])
                new_css.append(replacements[i])
                last_pos = match.end()
            new_css.append(css_content[last_pos:])
            
            return ''.join(new_css)
        except Exception as e:
            logger.error(f"处理CSS URLs时出错: {e}")
            return css_content  # 如果出错，返回原始CSS
    
    async def save_html_to_file(self, html_content: str, url: str, page_dir: str) -> str:
        """
        将HTML内容保存到临时文件
        """
        # 创建安全的文件名
        domain = self.extract_domain(url)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{domain}_{timestamp}.html"
        
        # 确保文件名安全
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)
        
        file_path = os.path.join(page_dir, filename)
        
        # 保存文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"HTML内容已保存到: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存HTML内容到文件时出错: {e}", exc_info=True)
            raise
    
    async def delete_file_later(self, file_path: str, delay: int):
        """
        延迟删除文件
        """
        try:
            await asyncio.sleep(delay)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"临时文件已删除: {file_path}")
        except Exception as e:
            logger.error(f"删除临时文件时出错: {e}", exc_info=True)
    
    async def delete_dir_later(self, dir_path: str, delay: int):
        """
        延迟删除目录（包括所有内容）
        """
        try:
            await asyncio.sleep(delay)
            if os.path.exists(dir_path):
                import shutil
                shutil.rmtree(dir_path)
                logger.info(f"临时目录已删除: {dir_path}")
        except Exception as e:
            logger.error(f"删除临时目录时出错: {e}", exc_info=True)
    
    async def cleanup_old_files(self):
        """
        清理旧的临时文件（超过1小时的文件和目录）
        """
        while True:
            try:
                current_time = datetime.now()
                one_hour_ago = current_time - timedelta(hours=1)
                
                if os.path.exists(self.save_dir):
                    for item_name in os.listdir(self.save_dir):
                        item_path = os.path.join(self.save_dir, item_name)
                        try:
                            if os.path.isfile(item_path):
                                file_modified_time = datetime.fromtimestamp(os.path.getmtime(item_path))
                                if file_modified_time < one_hour_ago:
                                    os.remove(item_path)
                                    logger.info(f"清理旧文件: {item_path}")
                            elif os.path.isdir(item_path):
                                # 检查目录的修改时间
                                dir_modified_time = datetime.fromtimestamp(os.path.getmtime(item_path))
                                if dir_modified_time < one_hour_ago:
                                    import shutil
                                    shutil.rmtree(item_path)
                                    logger.info(f"清理旧目录: {item_path}")
                        except Exception as e:
                            logger.warning(f"清理 {item_path} 时出错: {e}")
                
                # 每30分钟检查一次
                await asyncio.sleep(1800)
            except Exception as e:
                logger.error(f"清理临时文件时出错: {e}", exc_info=True)
                await asyncio.sleep(1800)
    
    def extract_domain(self, url: str) -> str:
        """
        从URL中提取域名
        """
        try:
            # 移除协议部分
            if "://" in url:
                url = url.split("://", 1)[1]
            
            # 移除路径部分
            if "/" in url:
                domain = url.split("/", 1)[0]
            else:
                domain = url
            
            # 移除端口号
            if ":" in domain:
                domain = domain.split(":", 1)[0]
            
            return domain
        except Exception as e:
            logger.error(f"提取域名时出错: {e}", exc_info=True)
            return "unknown"
    
    def is_valid_url(self, url: str) -> bool:
        """
        验证URL格式
        """
        # 如果没有协议，添加默认协议以便验证
        test_url = url if url.startswith(('http://', 'https://')) else 'https://' + url
        
        pattern = re.compile(
            r'^https?://'  # http:// 或 https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # 域名
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP地址
            r'(?::\d+)?'  # 可选端口
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return test_url is not None and pattern.match(test_url)
    
    async def terminate(self):
        """
        插件终止时的清理工作
        """
        if hasattr(self, 'cleanup_task') and self.cleanup_task:
            self.cleanup_task.cancel()
        
        # 注意：不删除 save_dir，因为可能还有未到期的文件
        # 清理任务会定期清理过期文件
        logger.info("HTMLPrint插件已终止")