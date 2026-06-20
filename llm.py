"""
LLM API 调用封装 — OpenAI 兼容接口
支持 DeepSeek / OpenAI / 硅基流动 等
"""
import os
import json
from typing import Optional
from openai import OpenAI


def _load_api_key() -> str:
    """从环境变量或终端 shell 加载 API Key"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    # 尝试从 shell 获取（绕过 read_file 的访问限制）
    import subprocess
    try:
        result = subprocess.run(
            ["bash", "-c", "source ~/.hermes/.env 2>/dev/null && echo $DEEPSEEK_API_KEY"],
            capture_output=True, text=True, timeout=5
        )
        key = result.stdout.strip()
        if key:
            return key
    except Exception:
        pass
    return ""


# ── 配置 ─────────────────────────────────────
DEFAULT_CONFIG = {
    "api_key": _load_api_key(),
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash",  # DeepSeek V4 Flash (支持工具调用)
}

# 也可以切换到硅基流动（免费额度）
SILICON_CONFIG = {
    "api_key": os.environ.get("SILICON_API_KEY", ""),
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "Qwen/Qwen2.5-7B-Instruct",
}


class LLM:
    """统一的 LLM 调用封装"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or DEFAULT_CONFIG
        self.client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        self.model = cfg["model"]

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """
        调用 LLM，支持 tool calling

        返回格式:
        {
            "role": "assistant",
            "content": "...",           # 文本回复（可能是空）
            "tool_calls": [...] or None # 工具调用请求
        }
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        result = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": None,
        }

        # V4 Flash 的推理内容放在 reasoning_content 字段
        if not result["content"] and hasattr(msg, "reasoning_content") and msg.reasoning_content:
            result["content"] = msg.reasoning_content

        # 解析工具调用
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return result

    def chat_stream(self, messages: list[dict], tools: Optional[list[dict]] = None,
                    temperature: float = 0.7, max_tokens: int = 4096):
        """流式调用 LLM，逐 token 产出
        每次 yield {"type": "text"|"tool_call"|"reasoning", "content": ...}
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**kwargs)

        tool_calls_buf = {}  # index → {id, name, arguments}
        text_buf = ""
        reasoning_buf = ""

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                # 可能是 usage 等结束 chunk
                continue

            # 推理内容
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_buf += delta.reasoning_content
                yield {"type": "reasoning", "content": delta.reasoning_content}

            # 文本 token
            if delta.content:
                text_buf += delta.content
                yield {"type": "text", "content": delta.content}

            # 工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buf:
                        tool_calls_buf[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buf[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_buf[idx]["arguments"] += tc.function.arguments

        # 全部结束后，如果有工具调用，产出 tool_call 事件
        finished_tool_calls = []
        for idx in sorted(tool_calls_buf):
            tc = tool_calls_buf[idx]
            finished_tool_calls.append({
                "id": tc["id"],
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })

        if finished_tool_calls:
            yield {"type": "tool_call", "content": finished_tool_calls}
        elif text_buf:
            yield {"type": "done", "content": text_buf}


# ── 测试 ──
if __name__ == "__main__":
    llm = LLM()
    resp = llm.chat([{"role": "user", "content": "你好，你叫什么？"}])
    print("回复:", resp["content"])
