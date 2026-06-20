"""核心 Agent 循环 — ReAct (Reasoning + Acting)
支持工具调用、多步推理、对话记忆 + 持久化
"""

import json
import os
from llm import LLM
from tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """你是一个有用的 AI 助手，配备了多种工具，可以回答问题、搜索网络、读写文件和管理知识库。

# 可用工具
- get_time: 获取当前时间
- calculate: 计算数学表达式
- web_search: 搜索网络获取实时信息
- read_file: 读取本地文件
- write_file: 写入本地文件
- list_files: 列出目录内容
- kb_search: 搜索个人知识库（笔记/文档）
- kb_add_file: 导入文件到知识库
- kb_add_text: 添加文本笔记到知识库
- kb_list: 查看知识库内容

# 工作方式
1. 当你需要信息或执行操作时，调用对应的工具
2. 你会看到工具返回的结果（Observation）
3. 根据结果决定下一步——要么继续调用工具，要么给出最终回答

# 重要规则
- 不知道答案时，先用 kb_search 搜索知识库，再用 web_search 搜索网络
- 工具可能返回错误，如实告诉用户
- 对于多步任务，分步思考，一步步执行
- 最终回答要清晰、完整、友好"""


class Agent:
    def __init__(self, llm: LLM, max_steps: int = 15, memory_size: int = 20):
        self.llm = llm
        self.max_steps = max_steps
        self.memory_size = memory_size  # 保留最近的 N 条对话
        self.history_dir = os.path.expanduser("~/agent_knowledge")
        self.history_path = os.path.join(self.history_dir, "chat_history.json")
        os.makedirs(self.history_dir, exist_ok=True)
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        self._load_history()

    def run(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

        for step in range(1, self.max_steps + 1):
            response = self.llm.chat(
                messages=self.messages,
                tools=TOOL_DEFINITIONS,
            )

            if response["content"]:
                print(f"  🤔 {response['content'][:100]}...")

            tool_calls = response.get("tool_calls")

            if not tool_calls:
                self.messages.append({
                    "role": "assistant",
                    "content": response["content"],
                })
                self._trim_memory()
                self._save_history()
                return response["content"]

            assistant_msg = {"role": "assistant", "content": response["content"]}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in tool_calls
            ]
            self.messages.append(assistant_msg)

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                print(f"  🔧 {name}({json.dumps(args, ensure_ascii=False)[:80]})")
                result = execute_tool(name, args)
                print(f"  📊 {result[:100]}...")

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return "抱歉，我未能完成这个任务。请尝试简化或拆分你的问题。"

    def reset(self):
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        # 同时清除持久化的历史文件
        if os.path.exists(self.history_path):
            os.remove(self.history_path)

    def _load_history(self):
        """从文件加载历史对话"""
        if not os.path.exists(self.history_path):
            return
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                past = json.load(f)
            # 只加载 user 和 assistant 消息，跳过 system（我们自己设）
            for msg in past:
                if msg["role"] in ("user", "assistant"):
                    self.messages.append(msg)
            if past:
                print(f"  💾 已加载 {len(past)} 条历史消息")
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    def _save_history(self):
        """将对话历史保存到文件（排除 system prompt）"""
        # 只保存 user + assistant 的消息，不保存 system 和 tool
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages
            if m["role"] in ("user", "assistant")
        ]
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def get_history(self):
        """返回用户可见的消息历史（给 Web 前端用）"""
        visible = []
        for m in self.messages:
            if m["role"] == "user":
                visible.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant" and m.get("content", "").strip():
                visible.append({"role": "assistant", "content": m["content"]})
        return visible

    def _trim_memory(self):
        """控制对话历史长度，避免 Token 超限"""
        # system + 最近的 memory_size 条消息
        system = [self.messages[0]]
        recent = self.messages[-self.memory_size:]
        self.messages = system + recent
