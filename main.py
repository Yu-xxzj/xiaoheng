"""
Mini Agent v2.0 — 交互式命令行入口
支持搜索、文件操作、多轮对话
"""

import sys
from llm import LLM
from agent import Agent


def print_banner():
    banner = """
╔══════════════════════════════════════════╗
║    🤖 Mini Agent v2.0                   ║
║    手写 ReAct Agent 框架                ║
║                                          ║
║  工具: 时间 / 计算 / 搜索 / 文件         ║
║                                          ║
║  /reset 重置  /tools 查看工具  /quit 退出║
╚══════════════════════════════════════════╝
"""
    print(banner)


def print_tools():
    tools_info = [
        "📋 可用工具:",
        "  🕐 get_time()       — 获取当前时间",
        "  🧮 calculate(expr)  — 数学计算 如 (15+8)*3-20",
        "  🌐 web_search(q)    — 搜索网络信息",
        "  📖 read_file(path)  — 读取本地文件",
        "  ✏️  write_file(path, content) — 写入本地文件",
        "  📁 list_files(path) — 列出目录内容",
    ]
    print("\n".join(tools_info))


def main():
    print_banner()

    print("正在连接 LLM...", end=" ", flush=True)
    try:
        llm = LLM()
        test = llm.chat([{"role": "user", "content": "ping"}])
        print(f"✅ {llm.model}")
    except Exception as e:
        print(f"❌ 失败: {e}")
        sys.exit(1)

    agent = Agent(llm=llm)
    print("Agent 已就绪！输入你的问题就好\n")

    while True:
        try:
            user_input = input("👤 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n再见！👋")
            break

        if not user_input:
            continue
        if user_input == "/quit":
            print("👋 再见！")
            break
        elif user_input == "/reset":
            agent.reset()
            print("🔄 对话已重置")
            continue
        elif user_input == "/tools":
            print_tools()
            continue

        try:
            print("🤖 思考中...")
            response = agent.run(user_input)
            print(f"\n🤖 {response}\n")
        except Exception as e:
            print(f"\n❌ 出错: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
