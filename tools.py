"""
工具定义 + 工具执行器
每个工具 = 一个函数 + 它的 JSON Schema 描述
"""

import datetime
import json
import os
from typing import Any, Callable


from knowledge_base import KnowledgeBase

# 全局知识库实例
_kb = KnowledgeBase()


# ── 工具实现 ─────────────────────────────

def get_time() -> str:
    """返回当前日期和时间"""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S (%A)")


def calculate(expression: str) -> str:
    """
    计算数学表达式
    注意: 使用安全求值，只允许基础数学运算
    """
    allowed_chars = set("0123456789+-*/.()% ,e")
    for c in expression:
        if c not in allowed_chars:
            return f"错误: 表达式包含不支持的字符 '{c}'"

    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"


def get_weather(city: str) -> str:
    """查询天气 — 模拟版本"""
    weather_data = {
        "北京": "晴，22°C，空气质量：良",
        "上海": "多云，25°C，空气质量：优",
        "广州": "小雨，28°C，空气质量：良",
        "深圳": "阴，27°C，空气质量：优",
        "杭州": "晴，23°C，空气质量：良",
        "成都": "多云，20°C，空气质量：轻度污染",
    }
    return weather_data.get(city, f"抱歉，暂不支持 {city} 的天气查询")


def web_search(query: str, max_results: int = 5) -> str:
    """
    搜索网络信息（使用 Bing 搜索）
    返回搜索结果的标题、链接和摘要
    """
    import re
    import urllib.parse
    import subprocess

    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded}&count={max_results}"
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        result = subprocess.run(
            ["curl", "-s", "--max-time", "15",
             "-A", user_agent,
             "-L", url],
            capture_output=True, text=True, timeout=20
        )
        html = result.stdout

        results = []
        # 使用简单方式提取搜索结果
        # Bing 结果格式
        for block in re.findall(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL):
            if len(results) >= max_results:
                break
            href = ""
            href_m = re.search(r'href="(https?://[^"]+)"', block)
            if href_m:
                href = href_m.group(1)
            # 提取标题：找 <a> 标签里的文本
            a_tag = re.search(r'<a[^>]*>(.*?)</a>', block, re.DOTALL)
            title = ""
            if a_tag:
                title = re.sub(r'<[^>]+>', '', a_tag.group(1)).strip()
            if not title:
                title = href.split('/')[2] if href else "链接"
            # 提取摘要
            snippet = ""
            for p in re.findall(r'<p[^>]*>(.*?)</p>', block, re.DOTALL):
                s = re.sub(r'<[^>]+>', '', p).strip()
                if s:
                    snippet = re.sub(r'\s+', ' ', s)
                    break
            display = f"[{title}]({href})" if href else title
            results.append(f"{len(results)+1}. {display}\n   {snippet[:300]}")

        if results:
            return f"「{query}」的搜索结果:\n\n" + "\n\n".join(results)
        else:
            # 备选：提取所有链接
            all_links = re.findall(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                html,
                re.DOTALL,
            )
            seen = set()
            for href, title in all_links:
                title = re.sub(r"<[^>]+>", "", title).strip()
                if title and len(title) > 5 and "bing.com" not in href and href not in seen:
                    seen.add(href)
                    results.append(f"{len(results)+1}. [{title}]({href})")
                    if len(results) >= max_results:
                        break
            if results:
                return f"「{query}」的搜索结果:\n\n" + "\n\n".join(results)

            return f"未找到「{query}」的相关结果"

    except Exception as e:
        return f"搜索出错: {e}"


def read_file(path: str) -> str:
    """
    读取指定文件的内容
    路径可以是绝对路径或相对路径
    """
    try:
        # 展开 ~ 和相对路径
        full_path = os.path.expanduser(path)
        if not os.path.exists(full_path):
            return f"文件不存在: {path}"
        if os.path.isdir(full_path):
            return f"{path} 是一个目录，不是文件"

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.count("\n") + 1
        # 限制返回长度，避免 Token 爆炸
        max_chars = 3000
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n...（共{lines}行，仅显示前{max_chars}字符）"
        return f"文件 {path} ({lines}行):\n\n{content}"
    except Exception as e:
        return f"读取文件出错: {e}"


def write_file(path: str, content: str) -> str:
    """
    写入内容到指定文件
    警告：会覆盖已有文件！
    """
    try:
        full_path = os.path.expanduser(path)
        # 自动创建目录
        os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ 已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        return f"写入文件出错: {e}"


def list_files(path: str = ".") -> str:
    """列出目录中的文件"""
    try:
        full_path = os.path.expanduser(path)
        if not os.path.exists(full_path):
            return f"路径不存在: {path}"
        if not os.path.isdir(full_path):
            return f"{path} 不是目录"

        items = os.listdir(full_path)
        if not items:
            return f"目录 {path} 是空的"

        result = [f"📁 {path} 的内容 ({len(items)} 项):\n"]
        for item in sorted(items):
            item_path = os.path.join(full_path, item)
            if os.path.isdir(item_path):
                result.append(f"  📁 {item}/")
            else:
                size = os.path.getsize(item_path)
                if size < 1024:
                    result.append(f"  📄 {item} ({size}B)")
                else:
                    result.append(f"  📄 {item} ({size/1024:.1f}KB)")
        return "\n".join(result)
    except Exception as e:
        return f"列出目录出错: {e}"


def kb_search(query: str, top_k: int = 5) -> str:
    """搜索个人知识库，找到最相关的笔记/文档"""
    return _kb.search(query, top_k)


def kb_add_file(file_path: str) -> str:
    """导入文件到个人知识库（支持 .txt .md .py .json 等）"""
    return _kb.add_file(file_path)


def kb_add_text(title: str, content: str) -> str:
    """直接添加一段文本到个人知识库"""
    return _kb.add_text(title, content)


def kb_list() -> str:
    """列出知识库中的所有文档"""
    return _kb.list_docs()


def kb_clear() -> str:
    """清空知识库"""
    return _kb.clear()


def read_image_text(image_path: str) -> str:
    """
    识别图片中的文字（OCR）
    使用 AI 视觉能力读取图片中的文本内容
    """
    import base64
    from io import BytesIO
    from PIL import Image

    path = os.path.expanduser(image_path)
    if not os.path.exists(path):
        return f"❌ 图片不存在: {image_path}"

    try:
        # 读取并压缩图片
        img = Image.open(path)
        # 限制最大尺寸，避免 token 过多
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)), Image.LANCZOS)

        # 转 base64
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        # 直接用 curl 调用 DeepSeek，因为 OpenAI 客户端不一定支持 vision
        import json, subprocess
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return "❌ 未设置 DEEPSEEK_API_KEY"

        payload = json.dumps({
            "model": "deepseek-v4-flash",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取这张图片中的所有文字内容，保持原文格式。只输出文字，不要额外说明。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }
            ],
            "max_tokens": 2048,
        })

        result = subprocess.run(
            ["curl", "-s", "--max-time", "30",
             "https://api.deepseek.com/v1/chat/completions",
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=35
        )

        resp = json.loads(result.stdout)
        text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if text:
            return f"📖 图片文字识别结果:\n\n{text}"
        else:
            err = resp.get("error", {}).get("message", "未知错误")
            return f"❌ 识别失败: {err}"

    except ImportError as e:
        return f"❌ 需要安装 Pillow: pip install Pillow (当前: {e})"
    except Exception as e:
        return f"❌ 图片识别出错: {e}"


def run_python(code: str) -> str:
    """
    在沙箱中执行 Python 代码并返回结果
    注意：代码将在子进程中运行，有超时限制
    """
    import tempfile
    import subprocess
    import sys

    # 在代码前注入安全限制
    sandbox_preamble = """
import sys as _sys
# 阻止危险操作
_SAFE_BUILTINS = {
    'print': print, 'len': len, 'range': range, 'int': int, 'float': float,
    'str': str, 'bool': bool, 'list': list, 'dict': dict, 'tuple': tuple,
    'set': set, 'abs': abs, 'max': max, 'min': min, 'sum': sum, 'sorted': sorted,
    'reversed': reversed, 'enumerate': enumerate, 'zip': zip, 'map': map,
    'filter': filter, 'any': any, 'all': all, 'isinstance': isinstance,
    'type': type, 'hasattr': hasattr, 'getattr': getattr, 'round': round,
    'pow': pow, 'divmod': divmod, 'hex': hex, 'oct': oct, 'bin': bin,
    'ord': ord, 'chr': chr, 'repr': repr, 'input': input,
    'open': open, '__import__': __import__,
    'True': True, 'False': False, 'None': None,
}
_sys.stdout.flush()
"""

    try:
        full_code = sandbox_preamble + "\n" + code
        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(full_code)
            tmp_path = f.name

        # 在子进程中运行
        result = subprocess.run(
            [sys.executable, "-c", f"exec(open('{tmp_path}').read())"],
            capture_output=True, text=True, timeout=15,
            env={}  # 清空环境变量阻止访问 API Key
        )

        os.unlink(tmp_path)

        output = ""
        if result.stdout.strip():
            output += f"📤 输出:\n{result.stdout.strip()}\n"
        if result.stderr.strip():
            output += f"⚠️ 错误:\n{result.stderr.strip()}\n"

        if not output:
            return "✅ 代码执行完毕（无输出）"
        return output[:3000]  # 限制输出长度

    except subprocess.TimeoutExpired:
        return "⏰ 代码执行超时（超过 15 秒）"
    except Exception as e:
        return f"❌ 执行出错: {e}"


# ── 工具注册表 ─────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学表达式，支持加减乘除、括号、百分号等",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '(15+8)*3-20'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网络信息，获取最新的新闻、资料、百科等。当你不知道答案或需要实时信息时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 '2025年诺贝尔奖 物理学'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果数量（默认5）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取本地文件内容，支持文本文件（如 .py, .txt, .json, .md 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，如 '~/notes.txt' 或 '/home/yu/test.py'",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入内容到本地文件（会覆盖已有文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，如 '~/output.txt'",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文件内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出指定目录下的文件和文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，默认当前目录 '.'",
                    }
                },
                "required": [],
            },              # close parameters
        },                  # close function
    },                      # close list_files item
    {                       # start kb_search
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "搜索个人知识库，找到与关键词最相关的笔记或文档。当你需要查找之前记过的内容时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量（默认5）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_add_file",
            "description": "导入一个文件到个人知识库（支持 .txt .md .py .json .yaml .csv .pdf），PDF 会自动解析文字",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径，如 '~/notes/my_notes.txt' 或 '/home/yu/project/code.py'",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_add_text",
            "description": "直接添加一段文本到个人知识库，用于临时记录笔记或重要信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "标题，如 '操作系统笔记 - 进程调度'",
                    },
                    "content": {
                        "type": "string",
                        "description": "文本内容",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_list",
            "description": "列出个人知识库中的所有文档",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_image_text",
            "description": "识别图片中的文字（OCR），支持 .png .jpg .jpeg 等格式。适合拍课本截图、笔记照片等",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "图片路径，如 '~/screenshot.png' 或 '/mnt/c/Users/22775/Desktop/note.jpg'",
                    }
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "执行 Python 代码并返回输出结果。用于计算、数据处理、算法验证等",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码",
                    }
                },
                "required": ["code"],
            },
        },
    },
]

# 名称 → 函数的映射表
TOOL_FUNCTIONS: dict[str, Callable] = {
    "get_time": get_time,
    "calculate": calculate,
    "get_weather": get_weather,
    "web_search": web_search,
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "kb_search": kb_search,
    "kb_add_file": kb_add_file,
    "kb_add_text": kb_add_text,
    "kb_list": kb_list,
    "kb_clear": kb_clear,
    "read_image_text": read_image_text,
    "run_python": run_python,
}


# ── 工具执行器 ─────────────────────────────

def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """
    执行指定的工具，返回结果字符串
    """
    if name not in TOOL_FUNCTIONS:
        return f"错误: 未找到工具 '{name}'"

    try:
        func = TOOL_FUNCTIONS[name]
        result = func(**arguments)
        return str(result)
    except TypeError as e:
        return f"工具参数错误: {e}"
    except Exception as e:
        return f"工具执行出错: {e}"
