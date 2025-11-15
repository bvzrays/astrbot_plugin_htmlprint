# HTML内容提取插件

一个用于AstrBot的插件，可以通过指令提取网页的完整内容（包括图片、CSS、JavaScript）并以文件形式发送。

## 功能特性

- 通过 `/html <网址>` 指令提取网页完整内容
- **自动下载并嵌入所有图片**：将网页中的图片转换为base64嵌入HTML，确保离线可查看
- **自动下载并嵌入CSS样式表**：下载所有外部CSS文件并转换为内联样式，保持页面样式
- **自动下载并嵌入JavaScript**：下载所有外部JS文件并转换为内联脚本，保持页面功能
- **处理CSS中的资源**：自动处理CSS中的背景图片、字体等资源
- **智能JavaScript渲染**：自动检测需要JavaScript渲染的页面（如React、Vue等SPA应用），使用Playwright浏览器渲染
- **图片转发消息**：在聊天中以转发消息（聊天记录）形式发送所有图片，方便查看
- 所有资源嵌入到HTML中，生成的文件可独立打开，无需网络连接
- 临时文件会在5分钟后自动删除
- 自动清理过期的临时文件
- 支持HTTP和HTTPS协议
- 异步处理，不阻塞其他操作

## 使用方法

发送指令：
```
/html https://www.example.com
```

或者：
```
/html http://www.example.com/path/to/page
```

插件会：
1. 获取指定网页的HTML内容
2. 自动下载所有图片、CSS、JavaScript等资源
3. 将所有资源转换为base64嵌入HTML
4. 在聊天中以转发消息形式发送所有图片
5. 发送包含完整资源的HTML文件
6. 5分钟后自动删除临时文件

## 安装依赖

```bash
pip install -r requirements.txt
```

### 依赖列表

- `aiohttp>=3.8.0` - 异步HTTP客户端，用于下载网页和资源
- `beautifulsoup4>=4.12.0` - HTML解析库，用于解析和修改HTML内容
- `playwright>=1.40.0` - 无头浏览器，用于渲染JavaScript动态内容（可选，但强烈推荐）

### 安装Playwright浏览器

安装Playwright后，还需要安装浏览器驱动：

```bash
# 安装Python包
pip install playwright

# 安装Chromium浏览器（用于渲染JavaScript）
playwright install chromium
```

**注意**：如果不安装Playwright，插件仍可正常工作，但无法处理需要JavaScript渲染的页面（如React、Vue等单页应用）。

## 配置说明

插件支持以下配置项（在 `_conf_schema.json` 中定义）：

- `enabled`: 是否启用插件（默认：true，类型：bool）

## 工作原理

1. **获取HTML**：
   - 首先使用aiohttp异步获取网页HTML内容
   - 自动检测页面是否为空白页面（需要JavaScript渲染）
   - 如果检测到需要JavaScript渲染，自动使用Playwright浏览器渲染页面
2. **解析资源**：使用BeautifulSoup解析HTML，查找所有外部资源
3. **下载资源**：
   - 图片：下载所有`<img>`标签中的图片
   - CSS：下载所有`<link rel="stylesheet">`中的样式表
   - JavaScript：下载所有`<script src="">`中的脚本文件
   - CSS资源：处理CSS中的`url()`引用（背景图片、字体等）
4. **嵌入资源**：
   - 图片：转换为base64格式的data URI
   - CSS：转换为内联`<style>`标签
   - JavaScript：转换为内联`<script>`标签
   - CSS中的资源：转换为base64格式的data URI
5. **发送内容**：
   - 在聊天中以转发消息形式发送所有图片
   - 发送包含所有嵌入资源的HTML文件

## 故障排除

如果遇到问题，请检查：

1. 确保提供的URL是有效的且可访问
2. 检查网络连接是否正常
3. 确认目标网站没有阻止爬虫访问
4. 某些网站可能使用动态加载内容，这些内容可能无法被捕获
5. 查看AstrBot的日志文件获取更多错误信息

## 注意事项

- 仅支持HTTP和HTTPS协议的网页
- 文件会在发送后5分钟内自动删除
- 插件会自动清理超过1小时的临时文件
- 对于大型网页或资源较多的网页，可能需要较长时间处理
- 某些网站可能有反爬虫机制，会导致获取失败
- 如果未安装Playwright，动态加载的内容（通过JavaScript异步加载）可能无法被捕获
- 安装了Playwright后，大部分JavaScript动态内容都可以被正确渲染
- 生成的HTML文件可能较大（因为所有资源都嵌入为base64）
- Playwright首次使用时会自动下载浏览器，可能需要一些时间

## 作者

bvzrays

## 版本

1.0.0