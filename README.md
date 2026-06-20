
> ⚡ **小珩** — 一个从零手写的 ReAct Agent 框架，具备知识库、工具调用、Web 界面和对话记忆。

<p align="center">
  <img src="assets/screenshot.png" alt="小珩界面截图" width="700">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?logo=python">
  <img src="https://img.shields.io/badge/DeepSeek-V4_Flash-4A90D9?logo=deepseek">
  <img src="https://img.shields.io/badge/License-MIT-green">
</p>

---

## 📋 目录

- [✨ 简介](#-简介)
- [🛠 功能](#-功能)
- [📸 截图](#-截图)
- [🚀 快速开始](#-快速开始)
- [🧠 架构](#-架构)
- [📁 项目结构](#-项目结构)
- [🎯 路线图](#-路线图)
- [📝 许可](#-许可)

---

## ✨ 简介

**小珩**（xiǎo héng，珩为古玉器名）是一个纯 Python 实现的个人 AI 助手框架，基于 **ReAct（Reasoning + Acting）** 范式，支持：

- 🤖 **LLM 驱动** — 集成 DeepSeek V4 Flash，支持函数调用（Function Calling）
- 📚 **个人知识库** — 纯 Python TF-IDF 语义搜索，无需任何外部数据库
- 🛠 **工具注册系统** — 插件式工具，方便扩展
- 💾 **对话持久化** — 关闭页面后仍可恢复历史聊天
- 🎨 **赛博科技风 UI** — 毛玻璃设计 + 粒子动画 + 响应式布局

> 适用于：个人知识管理、学习笔记检索、AI 对话实验、Agent 框架学习

---

## 🛠 功能

| 功能 | 描述 |
|------|------|
| 🧠 **ReAct 推理** | 多步思考 + 工具调用循环，最大 15 步 |
| 📚 **知识库搜索** | TF-IDF 语义搜索，支持中文/英文分词 |
| 📄 **文件导入** | 支持 `.txt` `.md` `.py` `.json` `.pdf` 自动导入并分段 |
| 📁 **批量导入** | 拖入整个文件夹，自动遍历全部支持的文件 |
| 🌐 **网络搜索** | 集成 Bing 搜索，获取实时信息 |
| 🧮 **数学计算** | 安全表达式求值 |
| 📖 **文件操作** | 读写文件、列出目录 |
| 💾 **对话记忆** | 持久化到 JSON，重启网页历史不丢 |
| 🖥 **Web 界面** | 毛玻璃粒子动效，响应式，移动端适配 |

---

## 📸 截图

<p align="center">
  <em>（截图待补充 — 运行后打开 http://localhost:8000 即可查看）</em>
</p>

| 主界面 | 知识库搜索 |
|:------:|:----------:|
| ![界面](assets/ui-main.png) | ![搜索](assets/ui-search.png) |

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- DeepSeek API Key（或其他兼容 OpenAI API 的模型）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/mini-agent.git
cd mini-agent

# 2. 安装依赖（纯 Python，仅需一个包）
pip install openai fastapi uvicorn pypdf

# 3. 配置 API Key
export DEEPSEEK_API_KEY="sk-你的key"
```

### 运行

```bash
# 终端模式
python3 main.py

# Web 界面模式
python3 -m uvicorn web_api:app --host 0.0.0.0 --port 8000
# 打开 http://localhost:8000
```

### 导入知识

打开 Web 界面后，直接跟小珩说：

```
导入这个文件：~/笔记/操作系统.txt
导入这个文件夹：~/课件/
搜索进程调度算法
记一下：Python装饰器的语法是 @decorator
```

---

## 🧠 架构

```
┌─────────────────────────────────────────────────┐
│                   Web UI                         │
│         (FastAPI + HTML/CSS/JS)                  │
└──────────────────┬──────────────────────────────┘
                   │ HTTP / JSON
┌──────────────────▼──────────────────────────────┐
│                   Agent                           │
│         ReAct 循环（思考 → 行动 → 观察）          │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │
│  │ System   │  │ 记忆管理  │  │  工具调度器     │ │
│  │ Prompt   │  │memory_size│  │ execute_tool()  │ │
│  └──────────┘  └──────────┘  └────────┬───────┘ │
└────────────────────────────────────────┬─────────┘
                                        │
         ┌──────────────────────────────┼──────────────┐
         │              ┌───────────────▼───────┐      │
         │              │       LLM 层           │      │
         │              │  DeepSeek API 调用      │      │
         │              │  Function Calling       │      │
         │              └───────────────────────┘      │
         │                                             │
┌────────▼────────┐  ┌────────▼────────┐  ┌─────────▼──┐
│   KnowledgeBase  │  │     Tools       │  │  Chat History│
│  TF-IDF 搜索引擎  │  │  时间/搜索/计算 │  │  持久化 JSON │
│  PDF 解析器       │  │  文件操作/天气  │  │             │
└─────────────────┘  └─────────────────┘  └────────────┘
```

### 核心流程

1. **用户输入** 进入 ReAct 循环
2. Agent 调用 LLM **思考**下一步行动
3. 需要信息时 → **调用工具**（搜索知识库 / 联网 / 计算）
4. **观察**工具返回结果
5. 重复步骤 2-4 直到给出最终回答
6. 对话历史 **自动持久化** 到文件

---

## 📁 项目结构

```
mini-agent/
├── agent.py              # ReAct 核心循环 + 对话管理
├── llm.py                # LLM API 封装（DeepSeek）
├── tools.py              # 工具定义 + 注册表 + 执行器
├── knowledge_base.py     # TF-IDF 知识库（纯 Python）
├── web_api.py            # FastAPI 后端 + Web UI
├── main.py               # 终端交互模式
├── seed_knowledge.py     # 示例笔记导入脚本
├── start_web.sh          # 一键启动 Web
├── requirements.txt      # 依赖清单
└── README.md             # 本文件
```

### 关键设计

| 文件 | 职责 |
|------|------|
| `agent.py` | ReAct 循环、对话记忆、历史持久化 |
| `llm.py` | LLM 调用、流式/非流式、Function Calling 解析 |
| `tools.py` | 工具实现、JSON Schema 定义、`execute_tool` 分发器 |
| `knowledge_base.py` | TF-IDF 向量搜索、PDF 解析、文档分块管理 |
| `web_api.py` | FastAPI 路由 + 赛博科技风前端（单页应用） |

---

## 🎯 路线图

- [x] ReAct 推理循环
- [x] 7 个内置工具（时间/计算/搜索/文件/天气）
- [x] TF-IDF 知识库搜索
- [x] PDF 导入支持
- [x] 对话历史持久化
- [x] 赛博科技风 Web UI
- [x] **流式输出** — WebSocket 逐 token 渲染，打字机效果
- [x] **OCR 图片识别** — 拍照/上传图片提取文字
- [ ] 多轮对话长期记忆
- [ ] 代码执行沙箱
- [ ] 多 Agent 协作

---

## 🧰 技术栈

| 技术 | 用途 |
|------|------|
| **Python 3.11** | 主语言 |
| **DeepSeek V4 Flash** | LLM + Function Calling |
| **FastAPI + Uvicorn** | Web 服务端 |
| **纯 CSS 动画** | 粒子系统、光效、毛玻璃 |
| **PyPDF** | PDF 文字提取 |
| **TF-IDF** | 语义搜索（纯 Python 实现） |

---

## 🤝 贡献

欢迎 Issue 和 PR！如果你想扩展功能：

1. 在 `tools.py` 添加新工具函数
2. 在 `TOOL_DEFINITIONS` 注册 JSON Schema
3. 在 `TOOL_FUNCTIONS` 添加函数映射
4. Agent 自动可用！

---

## 📝 许可

MIT License © 2025 小珩

---

<p align="center">
  <strong>从零手写 Agent · 不止于调包</strong>
  <br>
  <sub>Built with ❤️ and Python</sub>
</p>
