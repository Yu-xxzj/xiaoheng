"""
Mini Agent Web API — FastAPI 后端
"""
import sys, os, json, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载 API Key
result = subprocess.run(
    ["bash", "-c", "source ~/.hermes/.env 2>/dev/null && echo $DEEPSEEK_API_KEY"],
    capture_output=True, text=True, timeout=10
)
key = result.stdout.strip()
if key:
    os.environ["DEEPSEEK_API_KEY"] = key

from llm import LLM
from agent import Agent
from tools import execute_tool, _kb as kb
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import tempfile
import uuid
import shutil

app = FastAPI(title="Mini Agent")

# 全局 Agent
llm = LLM()
agent = Agent(llm=llm)

# 上传目录（存放拍照上传的图片）
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# 挂载静态文件路由，让上传的图片可以访问
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


class ChatRequest(BaseModel):
    message: str


class ResetRequest(BaseModel):
    pass


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(HTML_PAGE)


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        response = agent.run(req.message)
        return {"response": response}
    except Exception as e:
        return {"response": f"❌ 出错: {e}"}


@app.post("/api/reset")
def reset():
    agent.reset()
    return {"response": "🔄 对话已重置"}


@app.get("/api/history")
def history():
    """返回历史消息（前端用来恢复聊天记录）"""
    return {"history": agent.get_history()}


@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """上传图片 -> 保存 -> OCR 识别文字"""
    # 保存上传的图片
    ext = os.path.splitext(file.filename or "photo.png")[1] or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # 调用 OCR 工具识别文字
    try:
        result = execute_tool("read_image_text", {"image_path": filepath})
    except Exception as e:
        result = f"❌ 识别失败: {e}"

    # 把 OCR 结果注入到 agent 的对话中，方便后续追问
    agent.messages.append({
        "role": "user",
        "content": f"我上传了一张图片，识别出的文字如下：\n\n{result}",
    })

    return {
        "ocr": result,
        "url": f"/uploads/{filename}",
    }


# ── 流式聊天 API (SSE) ─────────────────────


@app.get("/api/chat/stream")
async def chat_stream_get(message: str = ""):
    """流式聊天 GET 版（给 EventSource 用）"""
    from fastapi.responses import StreamingResponse

    async def event_generator():
        try:
            for event in agent.run_stream(message):
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── WebSocket 流式聊天（绕过 HTTP 缓冲，真正逐字输出）───


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        msg = json.loads(data).get("message", "")
        if not msg:
            await websocket.send_json({"type": "error", "content": "消息为空"})
            return

        for event in agent.run_stream(msg):
            await websocket.send_json(event)

        await websocket.send_json({"type": "done", "content": ""})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except RuntimeError:
            pass


# ── 知识库管理 API ─────────────────────────


@app.get("/api/kb/list")
def kb_list():
    """获取知识库文档列表"""
    docs = kb.documents[:200]  # 最多200条
    return {"documents": docs, "total": len(kb.documents)}


class KBSearchRequest(BaseModel):
    query: str
    top_k: int = 20


@app.post("/api/kb/search")
def kb_search(req: KBSearchRequest):
    """搜索知识库"""
    results = kb.search_raw(req.query, req.top_k)
    items = [{"doc": doc, "score": round(score, 4)} for doc, score in results]
    return {"results": items}


@app.get("/api/kb/doc/{doc_id}")
def kb_get_doc(doc_id: str):
    """获取单篇文档"""
    doc = kb.get_doc(doc_id)
    if doc is None:
        return {"error": "文档不存在"}
    return {"doc": doc}


@app.post("/api/kb/delete/{doc_id}")
def kb_delete(doc_id: str):
    """删除文档"""
    ok = kb.delete_doc(doc_id)
    return {"success": ok}


class KBEditRequest(BaseModel):
    title: str = None
    content: str = None


@app.post("/api/kb/edit/{doc_id}")
def kb_edit(doc_id: str, req: KBEditRequest):
    """编辑文档"""
    ok = kb.update_doc(doc_id, title=req.title, content=req.content)
    return {"success": ok}


class KBAddTextRequest(BaseModel):
    title: str
    content: str


@app.post("/api/kb/add")
def kb_add_text(req: KBAddTextRequest):
    """添加文本笔记"""
    result = kb.add_text(req.title, req.content)
    return {"success": True, "message": result}


@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile = File(...)):
    """上传文件到知识库"""
    suffix = os.path.splitext(file.filename or "doc.txt")[1] or ".txt"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb")
    content = await file.read()
    tmp.write(content)
    tmp_path = tmp.name
    tmp.close()

    result = kb.add_file(tmp_path)
    os.unlink(tmp_path)  # 清理临时文件
    return {"success": True, "message": result}


# ====== HTML 前端（赛博科技风）======
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小珩 · AI 助手</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        @keyframes aurora {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        body {
            font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background: linear-gradient(-45deg, #0a0a1a, #0d0d2b, #1a0a2e, #0a1628, #0d0d2b);
            background-size: 600% 600%;
            animation: aurora 25s ease infinite;
            overflow: hidden;
        }

        /* Canvas 粒子背景 */
        #particleCanvas {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            pointer-events: none;
            z-index: 0;
        }

        /* 发光氛围球 */
        .glow-orb {
            position: fixed;
            border-radius: 50%;
            filter: blur(80px);
            pointer-events: none;
            z-index: 0;
        }
        .glow-orb.g1 {
            width: 400px; height: 400px;
            background: rgba(100, 60, 255, 0.12);
            top: -100px; right: -100px;
            animation: floatOrb 8s ease-in-out infinite;
        }
        .glow-orb.g2 {
            width: 350px; height: 350px;
            background: rgba(0, 200, 255, 0.08);
            bottom: -80px; left: -80px;
            animation: floatOrb 10s ease-in-out infinite reverse;
        }
        .glow-orb.g3 {
            width: 250px; height: 250px;
            background: rgba(255, 100, 200, 0.06);
            top: 40%; left: 50%;
            animation: floatOrb 12s ease-in-out infinite 2s;
        }
        @keyframes floatOrb {
            0%, 100% { transform: translate(0, 0) scale(1); }
            33% { transform: translate(30px, -30px) scale(1.1); }
            66% { transform: translate(-20px, 20px) scale(0.9); }
        }

        .container {
            position: relative;
            z-index: 1;
            width: 100%;
            max-width: 780px;
            height: 92vh;
            display: flex;
            flex-direction: column;
            background: rgba(10, 10, 28, 0.7);
            backdrop-filter: blur(30px);
            -webkit-backdrop-filter: blur(30px);
            border: 1px solid rgba(100, 100, 255, 0.12);
            border-radius: 24px;
            box-shadow:
                0 0 80px rgba(80, 80, 255, 0.06),
                inset 0 1px 0 rgba(255, 255, 255, 0.05);
            overflow: hidden;
        }

        /* 顶部渐变光条 */
        .top-glow {
            height: 2px;
            background: linear-gradient(90deg,
                transparent,
                rgba(100, 100, 255, 0.3),
                rgba(0, 200, 255, 0.3),
                rgba(255, 100, 200, 0.3),
                transparent);
            flex-shrink: 0;
            animation: glowShift 3s ease-in-out infinite;
        }
        @keyframes glowShift {
            0%, 100% { filter: hue-rotate(0deg); opacity: 0.6; }
            50% { filter: hue-rotate(30deg); opacity: 1; }
        }

        /* ── 标题栏 ── */
        header {
            padding: 14px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .header-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .logo-wrap {
            position: relative;
            width: 40px; height: 40px;
        }
        .logo-ring {
            position: absolute;
            inset: -3px;
            border-radius: 12px;
            border: 1.5px solid transparent;
            background: linear-gradient(135deg, #6c6cff, #00ccff, #ff6cff) border-box;
            -webkit-mask: linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0);
            mask: linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
            animation: spin 4s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .logo-icon {
            width: 40px; height: 40px;
            border-radius: 10px;
            background: linear-gradient(135deg, #5c5cff, #3a3aff);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            box-shadow: 0 0 24px rgba(100, 100, 255, 0.25);
        }
        .header-title h1 {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 1px;
        }
        .header-title h1 .hi { color: #e8e8ff; }
        .header-title h1 .heng { color: #7c7cff; }
        .header-title .desc {
            font-size: 11px;
            background: linear-gradient(90deg, #7c7cff, #00ccff, #7c7cff);
            background-size: 200% 100%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: shimmer 3s ease-in-out infinite;
            letter-spacing: 2px;
        }
        @keyframes shimmer {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }
        .header-actions { display: flex; gap: 8px; }
        .btn-reset {
            padding: 7px 16px;
            border: 1px solid rgba(255, 80, 80, 0.25);
            border-radius: 8px;
            background: rgba(255, 80, 80, 0.06);
            color: rgba(255, 100, 100, 0.7);
            font-size: 12px;
            cursor: pointer;
            transition: all 0.25s;
        }
        .btn-reset:hover {
            background: rgba(255, 80, 80, 0.15);
            border-color: rgba(255, 80, 80, 0.4);
            box-shadow: 0 0 20px rgba(255, 80, 80, 0.12);
            color: #ff6b6b;
        }

        /* ── 状态栏 ── */
        .status-bar {
            padding: 6px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
            border-top: 1px solid rgba(100, 100, 255, 0.05);
            border-bottom: 1px solid rgba(100, 100, 255, 0.05);
            flex-shrink: 0;
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            color: rgba(180, 180, 255, 0.35);
        }
        .dot {
            width: 6px; height: 6px;
            border-radius: 50%;
            display: inline-block;
        }
        .dot.green {
            background: #4caf50;
            box-shadow: 0 0 6px rgba(76, 175, 80, 0.6);
        }
        .dot.pulse { animation: pulse 2s ease-in-out infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .status-divider {
            width: 1px; height: 12px;
            background: rgba(100, 100, 255, 0.08);
        }
        .kb-count {
            color: rgba(180, 180, 255, 0.35);
            font-size: 11px;
            margin-left: auto;
        }

        /* ── 聊天区 ── */
        .chat-box {
            flex: 1;
            overflow-y: auto;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 18px;
            scroll-behavior: smooth;
        }
        .chat-box::-webkit-scrollbar { width: 4px; }
        .chat-box::-webkit-scrollbar-track { background: transparent; }
        .chat-box::-webkit-scrollbar-thumb {
            background: rgba(100, 100, 255, 0.15);
            border-radius: 2px;
        }
        .chat-box::-webkit-scrollbar-thumb:hover {
            background: rgba(100, 100, 255, 0.3);
        }

        .msg-row {
            display: flex;
            align-items: flex-end;
            gap: 10px;
            animation: msgIn 0.35s ease-out;
        }
        @keyframes msgIn {
            from { opacity: 0; transform: translateY(16px) scale(0.96); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        .msg-row.user { flex-direction: row-reverse; }

        .avatar {
            width: 32px; height: 32px;
            border-radius: 50%;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }
        .avatar.bot {
            background: linear-gradient(135deg, #3a3a7a, #5a3aaa);
            border: 1px solid rgba(100, 100, 255, 0.2);
            box-shadow: 0 0 12px rgba(100, 100, 255, 0.15);
        }
        .avatar.user {
            background: linear-gradient(135deg, #2a5a8a, #3a3a7a);
            border: 1px solid rgba(100, 150, 255, 0.2);
        }

        .msg-wrap {
            max-width: 75%;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .msg-wrap.user { align-items: flex-end; }

        .msg {
            padding: 11px 16px;
            border-radius: 16px;
            line-height: 1.65;
            font-size: 14px;
            position: relative;
        }
        .msg-row.user .msg {
            background: linear-gradient(135deg,
                rgba(60, 60, 180, 0.5),
                rgba(100, 50, 220, 0.35));
            border: 1px solid rgba(100, 80, 255, 0.15);
            color: #e0e0ff;
            border-bottom-right-radius: 4px;
        }
        .msg-row.bot .msg {
            background: rgba(18, 18, 48, 0.6);
            border: 1px solid rgba(100, 100, 255, 0.08);
            color: #d0d0e8;
            border-bottom-left-radius: 4px;
        }
        .msg-row.bot .msg a {
            color: #7c7cff;
            text-decoration: none;
            border-bottom: 1px dotted rgba(100,100,255,0.3);
            transition: color 0.2s;
        }
        .msg-row.bot .msg a:hover { color: #b0b0ff; }
        .msg-row.bot .msg code {
            background: rgba(0, 0, 0, 0.3);
            padding: 2px 8px;
            border-radius: 5px;
            font-size: 13px;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            color: #90d0ff;
            border: 1px solid rgba(100, 100, 255, 0.1);
        }
        .msg-row.bot .msg pre {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(100, 100, 255, 0.08);
            border-radius: 10px;
            padding: 14px;
            margin: 8px 0;
            overflow-x: auto;
        }
        .msg-row.bot .msg pre code {
            background: none; padding: 0; border: none;
            font-size: 13px; line-height: 1.6;
        }
        .msg-row.bot .msg strong { color: #b0b0ff; }
        .msg-row.bot .msg em { color: #9090c0; }

        .msg-time {
            font-size: 10px;
            color: rgba(180, 180, 255, 0.15);
            padding: 0 4px;
        }

        .typing-row {
            display: flex;
            align-items: flex-end;
            gap: 10px;
            animation: msgIn 0.3s ease-out;
        }
        .typing-bubbles {
            display: flex;
            gap: 4px;
            padding: 14px 20px;
            background: rgba(18, 18, 48, 0.5);
            border: 1px solid rgba(100, 100, 255, 0.06);
            border-radius: 16px;
            border-bottom-left-radius: 4px;
        }
        .typing-bubbles span {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: rgba(100, 100, 255, 0.4);
            animation: tb 1.4s ease-in-out infinite;
        }
        .typing-bubbles span:nth-child(2) { animation-delay: 0.2s; }
        .typing-bubbles span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes tb {
            0%, 60%, 100% { transform: translateY(0); opacity: 0.3; }
            30% { transform: translateY(-8px); opacity: 1; }
        }

        /* ── 输入区 ── */
        .input-area {
            padding: 14px 24px 18px;
            border-top: 1px solid rgba(100, 100, 255, 0.06);
            display: flex;
            gap: 10px;
            flex-shrink: 0;
            background: rgba(6, 6, 20, 0.3);
        }
        .input-wrap {
            flex: 1;
            position: relative;
        }
        .input-wrap input {
            width: 100%;
            padding: 13px 18px;
            border: 1px solid rgba(100, 100, 255, 0.12);
            border-radius: 14px;
            background: rgba(12, 12, 36, 0.5);
            color: #d0d0f0;
            font-size: 14px;
            outline: none;
            transition: all 0.3s;
            font-family: inherit;
        }
        .input-wrap input::placeholder {
            color: rgba(180, 180, 255, 0.18);
        }
        .input-wrap input:focus {
            border-color: rgba(100, 100, 255, 0.3);
            box-shadow: 0 0 30px rgba(80, 80, 255, 0.06), inset 0 0 16px rgba(80, 80, 255, 0.02);
        }
        .input-area button {
            padding: 13px 28px;
            border: none;
            border-radius: 14px;
            background: linear-gradient(135deg, #5c5cff, #7c3aff);
            color: #fff;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            letter-spacing: 0.5px;
            white-space: nowrap;
            box-shadow: 0 0 24px rgba(80, 80, 255, 0.12);
        }
        .input-area button:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 0 40px rgba(80, 80, 255, 0.25);
        }
        .input-area button:active:not(:disabled) { transform: translateY(0); }
        .input-area button:disabled {
            background: linear-gradient(135deg, #2a2a4a, #3a2a5a);
            box-shadow: none; cursor: not-allowed; opacity: 0.4;
        }

        /* ── 拍照/上传按钮 ── */
        .btn-camera {
            width: 44px; height: 44px;
            border: 1px solid rgba(100, 100, 255, 0.15);
            border-radius: 14px;
            background: rgba(12, 12, 36, 0.5);
            color: rgba(180, 180, 255, 0.4);
            font-size: 20px;
            cursor: pointer;
            transition: all 0.25s;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .btn-camera:hover {
            border-color: rgba(100, 100, 255, 0.3);
            background: rgba(20, 20, 50, 0.6);
            color: rgba(200, 200, 255, 0.7);
            box-shadow: 0 0 20px rgba(80, 80, 255, 0.08);
        }
        .btn-camera:active { transform: scale(0.95); }

        /* ── 知识库管理侧栏 ── */
        .kb-overlay {
            position: fixed; inset: 0;
            background: rgba(0,0,0,0.5);
            z-index: 99;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
        }
        .kb-overlay.show {
            opacity: 1;
            pointer-events: auto;
        }

        .btn-kb {
            padding: 7px 14px;
            border: 1px solid rgba(100, 100, 255, 0.2);
            border-radius: 8px;
            background: rgba(80, 80, 200, 0.08);
            color: rgba(180, 180, 255, 0.7);
            font-size: 12px;
            cursor: pointer;
            transition: all 0.25s;
        }
        .btn-kb:hover {
            background: rgba(80, 80, 200, 0.18);
            border-color: rgba(100, 100, 255, 0.35);
            color: #c0c0ff;
        }

        .kb-panel {
            position: fixed; top: 0; right: 0;
            width: 420px; max-width: 90vw;
            height: 100vh;
            background: rgba(10, 10, 28, 0.92);
            backdrop-filter: blur(30px);
            -webkit-backdrop-filter: blur(30px);
            border-left: 1px solid rgba(100, 100, 255, 0.1);
            z-index: 100;
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: -10px 0 60px rgba(0, 0, 0, 0.4);
        }
        .kb-panel.show { transform: translateX(0); }

        .kb-panel-header {
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(100, 100, 255, 0.08);
            flex-shrink: 0;
            font-size: 16px;
            font-weight: 700;
            color: #c0c0f0;
        }
        .kb-close {
            width: 32px; height: 32px;
            border: 1px solid rgba(100, 100, 255, 0.1);
            border-radius: 8px;
            background: transparent;
            color: rgba(180, 180, 255, 0.4);
            font-size: 16px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .kb-close:hover {
            background: rgba(255, 80, 80, 0.1);
            border-color: rgba(255, 80, 80, 0.3);
            color: #ff6b6b;
        }

        .kb-search {
            padding: 12px 20px;
            flex-shrink: 0;
        }
        .kb-search input {
            width: 100%;
            padding: 10px 16px;
            border: 1px solid rgba(100, 100, 255, 0.1);
            border-radius: 10px;
            background: rgba(12, 12, 36, 0.5);
            color: #d0d0f0;
            font-size: 13px;
            outline: none;
            transition: all 0.25s;
            font-family: inherit;
        }
        .kb-search input:focus {
            border-color: rgba(100, 100, 255, 0.3);
            box-shadow: 0 0 20px rgba(80, 80, 255, 0.05);
        }
        .kb-search input::placeholder { color: rgba(180, 180, 255, 0.15); }

        .kb-stats {
            padding: 0 20px 8px;
            font-size: 11px;
            color: rgba(180, 180, 255, 0.25);
            flex-shrink: 0;
        }

        .kb-actions {
            padding: 4px 20px 12px;
            display: flex;
            gap: 8px;
            flex-shrink: 0;
            border-bottom: 1px solid rgba(100, 100, 255, 0.05);
        }
        .kb-actions button {
            flex: 1;
            padding: 9px 12px;
            border: 1px solid rgba(100, 100, 255, 0.12);
            border-radius: 8px;
            background: rgba(80, 80, 200, 0.05);
            color: rgba(180, 180, 255, 0.6);
            font-size: 12px;
            cursor: pointer;
            transition: all 0.25s;
            font-family: inherit;
        }
        .kb-actions button:hover {
            background: rgba(80, 80, 200, 0.15);
            border-color: rgba(100, 100, 255, 0.3);
            color: #c0c0ff;
        }

        /* ── 文档列表 ── */
        .kb-list {
            flex: 1;
            overflow-y: auto;
            padding: 4px 0;
        }
        .kb-list::-webkit-scrollbar { width: 3px; }
        .kb-list::-webkit-scrollbar-thumb { background: rgba(100, 100, 255, 0.15); border-radius: 2px; }

        .kb-list-item {
            padding: 12px 20px;
            cursor: pointer;
            transition: all 0.2s;
            border-bottom: 1px solid rgba(100, 100, 255, 0.03);
        }
        .kb-list-item:hover {
            background: rgba(80, 80, 200, 0.06);
        }
        .kb-list-item.active {
            background: rgba(80, 80, 200, 0.1);
            border-left: 2px solid rgba(100, 100, 255, 0.3);
        }
        .kb-list-item .kb-item-title {
            font-size: 13px;
            color: #c0c0f0;
            font-weight: 600;
            margin-bottom: 3px;
        }
        .kb-list-item .kb-item-preview {
            font-size: 11px;
            color: rgba(180, 180, 255, 0.25);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .kb-list-item .kb-item-score {
            font-size: 10px;
            color: rgba(100, 200, 100, 0.3);
            margin-left: 8px;
        }
        .kb-empty {
            padding: 40px 20px;
            text-align: center;
            color: rgba(180, 180, 255, 0.15);
            font-size: 13px;
        }

        /* ── 文档详情 ── */
        .kb-detail {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .kb-detail::-webkit-scrollbar { width: 3px; }
        .kb-detail::-webkit-scrollbar-thumb { background: rgba(100, 100, 255, 0.15); border-radius: 2px; }

        .kb-detail .kb-detail-title {
            font-size: 16px;
            font-weight: 700;
            color: #d0d0ff;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(100, 100, 255, 0.08);
        }
        .kb-detail .kb-detail-source {
            font-size: 11px;
            color: rgba(180, 180, 255, 0.2);
        }
        .kb-detail .kb-detail-content {
            font-size: 13px;
            line-height: 1.8;
            color: #b0b0d0;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .kb-detail-actions {
            display: flex;
            gap: 8px;
            padding-top: 8px;
        }
        .kb-detail-actions button {
            padding: 7px 16px;
            border: 1px solid rgba(100, 100, 255, 0.12);
            border-radius: 8px;
            background: rgba(80, 80, 200, 0.05);
            color: rgba(180, 180, 255, 0.6);
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
        }
        .kb-detail-actions button:hover { background: rgba(80, 80, 200, 0.15); color: #c0c0ff; }
        .kb-detail-actions .btn-del:hover {
            background: rgba(255, 80, 80, 0.1);
            border-color: rgba(255, 80, 80, 0.3);
            color: #ff6b6b;
        }
        .kb-back {
            padding: 7px 14px;
            border: none;
            background: transparent;
            color: rgba(180, 180, 255, 0.3);
            font-size: 12px;
            cursor: pointer;
            transition: color 0.2s;
            font-family: inherit;
        }
        .kb-back:hover { color: rgba(180, 180, 255, 0.6); }

        /* ── 编辑/新建表单 ── */
        .kb-edit-form {
            flex: 1;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            overflow-y: auto;
        }
        .kb-edit-form label {
            font-size: 12px;
            color: rgba(180, 180, 255, 0.3);
        }
        .kb-edit-form input,
        .kb-edit-form textarea {
            width: 100%;
            padding: 10px 14px;
            border: 1px solid rgba(100, 100, 255, 0.1);
            border-radius: 8px;
            background: rgba(12, 12, 36, 0.5);
            color: #d0d0f0;
            font-size: 13px;
            outline: none;
            font-family: inherit;
            transition: border-color 0.2s;
        }
        .kb-edit-form textarea {
            min-height: 200px;
            resize: vertical;
            line-height: 1.6;
        }
        .kb-edit-form input:focus,
        .kb-edit-form textarea:focus {
            border-color: rgba(100, 100, 255, 0.3);
        }
        .kb-edit-form .form-actions {
            display: flex;
            gap: 8px;
        }
        .kb-edit-form .form-actions button {
            flex: 1;
            padding: 10px;
            border: 1px solid rgba(100, 100, 255, 0.12);
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
        }
        .kb-edit-form .btn-save {
            background: linear-gradient(135deg, #5c5cff, #7c3aff);
            color: #fff;
            border: none !important;
        }
        .kb-edit-form .btn-save:hover { box-shadow: 0 0 20px rgba(80, 80, 255, 0.2); }
        .kb-edit-form .btn-cancel {
            background: transparent;
            color: rgba(180, 180, 255, 0.4);
        }
        .kb-edit-form .btn-cancel:hover {
            background: rgba(80, 80, 200, 0.1);
            color: rgba(180, 180, 255, 0.6);
        }

        /* ── 底部署名 ── */
        .footer {
            text-align: center;
            padding: 5px 0 9px;
            font-size: 10px;
            color: rgba(180, 180, 255, 0.08);
            letter-spacing: 4px;
            flex-shrink: 0;
        }

        /* ── 手机端适配 ── */
        @media (max-width: 768px) {
            body {
                background: linear-gradient(-45deg, #0a0a1a, #0d0d2b, #1a0a2e, #0a1628, #0d0d2b);
                background-size: 400% 400%;
                animation: aurora 15s ease infinite;
                overflow: hidden;
                /* 禁止下拉刷新 */
                overscroll-behavior: none;
                -webkit-overflow-scrolling: touch;
            }
            /* 手机上关掉粒子 Canvas */
            #particleCanvas { display: none; }
            /* 手机上去掉大光球（太耗性能） */
            .glow-orb { display: none; }
            .container {
                height: 100dvh;
                border-radius: 0;
                max-width: 100%;
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
            }
            .top-glow { height: 1px; }
            header { padding: 10px 14px; }
            .logo-icon { width: 32px; height: 32px; font-size: 16px; }
            .logo-wrap { width: 32px; height: 32px; }
            .logo-ring { display: none; }
            .header-title h1 { font-size: 15px; }
            .header-title .desc { font-size: 10px; }
            .btn-reset { padding: 5px 12px; font-size: 11px; }
            .status-bar { padding: 4px 14px; gap: 10px; font-size: 10px; }
            .status-divider { display: none; }
            .chat-box {
                padding: 12px 14px;
                gap: 12px;
                /* 让键盘弹出时聊天区可滚动 */
                overflow-y: auto;
            }
            .msg-wrap { max-width: 88%; }
            .msg {
                padding: 10px 13px;
                font-size: 14px;
                line-height: 1.6;
                border-radius: 14px;
            }
            .msg-row.user .msg { border-bottom-right-radius: 4px; }
            .msg-row.bot .msg { border-bottom-left-radius: 4px; }
            .avatar { width: 28px; height: 28px; font-size: 12px; }
            .msg-time { font-size: 9px; }
            .typing-bubbles { padding: 11px 16px; }
            .input-area {
                padding: 10px 14px 14px;
                gap: 8px;
            }
            .input-wrap input {
                padding: 11px 14px;
                font-size: 16px;  /* 防止 iOS 缩放 */
                border-radius: 12px;
            }
            .input-area button {
                padding: 11px 20px;
                font-size: 14px;
                border-radius: 12px;
            }
            .btn-camera {
                width: 40px; height: 40px;
                border-radius: 12px;
                font-size: 18px;
            }
            /* 手机端 KB 面板全屏 */
            .kb-panel {
                width: 100vw !important;
                border-radius: 0 !important;
                border-left: none !important;
            }
            .kb-panel-header { padding: 14px 16px; }
            .kb-search input { font-size: 16px; padding: 10px 14px; }
            .kb-list-item { padding: 12px 16px; }
            .kb-detail { padding: 16px; }
            .kb-edit-form { padding: 16px; }
            .footer { display: none; }
        }
    </style>
</head>
<body>
<canvas id="particleCanvas"></canvas>
<div class="glow-orb g1"></div>
<div class="glow-orb g2"></div>
<div class="glow-orb g3"></div>

<div class="container">
    <div class="top-glow"></div>

    <header>
        <div class="header-left">
            <div class="logo-wrap">
                <div class="logo-ring"></div>
                <div class="logo-icon">✦</div>
            </div>
            <div class="header-title">
                <h1><span class="hi">小</span><span class="heng">珩</span></h1>
                <div class="desc">AI · KNOWLEDGE · REACT</div>
            </div>
        </div>
        <div class="header-actions">
            <button class="btn-kb" onclick="toggleKbPanel()">📚 知识库</button>
            <button class="btn-reset" onclick="resetChat()">⟳ 重置</button>
        </div>
    </header>

    <div class="status-bar">
        <span class="dot green pulse"></span>
        <span class="status-item">在线</span>
        <span class="status-divider"></span>
        <span class="status-item">📚 知识库</span>
        <span class="status-divider"></span>
        <span class="status-item">🔧 ReAct</span>
        <span class="kb-count" id="kbCount"></span>
    </div>

    <div class="chat-box" id="chatBox"></div>

    <div class="input-area">
        <button class="btn-camera" id="cameraBtn" onclick="document.getElementById('fileInput').click()" title="拍照/上传图片">📷</button>
        <input type="file" id="fileInput" accept="image/*" capture="environment" style="display:none" onchange="uploadImage(this)">
        <div class="input-wrap">
            <input type="text" id="input" placeholder="输入你的问题..." autofocus>
        </div>
        <button id="sendBtn" onclick="send()">发送 ▸</button>
    </div>

    <div class="footer">✧ MINI AGENT FRAMEWORK ✧</div>
</div>

<!-- 知识库管理侧栏 -->
<div class="kb-overlay" id="kbOverlay" onclick="toggleKbPanel()"></div>
<div class="kb-panel" id="kbPanel">
    <div class="kb-panel-header">
        <span>📚 知识库</span>
        <button class="kb-close" onclick="toggleKbPanel()">✕</button>
    </div>
    <div class="kb-search">
        <input type="text" id="kbSearch" placeholder="🔍 搜索知识库..." oninput="kbSearchDocs(this.value)">
    </div>
    <div class="kb-stats" id="kbStats">加载中...</div>
    <div class="kb-actions">
        <button onclick="kbShowAddForm()">✏️ 新建笔记</button>
        <button onclick="document.getElementById('kbFileInput').click()">📄 导入文件</button>
        <input type="file" id="kbFileInput" accept=".txt,.md,.py,.json,.yaml,.csv,.pdf" style="display:none" onchange="kbUploadFile(this)" multiple>
    </div>
    <div class="kb-list" id="kbList"></div>
    <div class="kb-detail" id="kbDetail" style="display:none"></div>
    <div class="kb-edit-form" id="kbEditForm" style="display:none"></div>
</div>

<script>
// ── 移动端兼容 ──
const isMobile = window.innerWidth < 768;

if (isMobile) {
    // 键盘弹出时滚动到输入框
    const inputEl = document.getElementById('input');
    inputEl.addEventListener('focus', () => {
        setTimeout(() => inputEl.scrollIntoView({ behavior: 'smooth' }), 300);
    });
    // 键盘收回时恢复
    inputEl.addEventListener('blur', () => {
        window.scrollTo(0, 0);
    });
}

// ── 粒子背景 ──
const canvas = document.getElementById('particleCanvas');
const ctx = canvas.getContext('2d');
let W, H, particles = [];

function resizeCanvas() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

const COUNT = 80;
for (let i = 0; i < COUNT; i++) {
    particles.push({
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 2 + 0.5,
        a: Math.random() * 0.4 + 0.1
    });
}

function drawParticles() {
    ctx.clearRect(0, 0, W, H);
    for (let p of particles) {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = W; if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H; if (p.y > H) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(180, 180, 255, ${p.a})`;
        ctx.fill();
    }
    // 连线
    for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
            const dx = particles[i].x - particles[j].x;
            const dy = particles[i].y - particles[j].y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 120) {
                ctx.beginPath();
                ctx.moveTo(particles[i].x, particles[i].y);
                ctx.lineTo(particles[j].x, particles[j].y);
                ctx.strokeStyle = `rgba(100, 100, 255, ${0.06 * (1 - dist / 120)})`;
                ctx.lineWidth = 0.5;
                ctx.stroke();
            }
        }
    }
    requestAnimationFrame(drawParticles);
}
drawParticles();

// ── 聊天 ──
const chatBox = document.getElementById('chatBox');
const input = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');

input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

function timeStr() {
    const d = new Date();
    return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

function addMsg(role, text) {
    const typing = document.querySelector('.typing-row');
    if (typing) typing.remove();

    const row = document.createElement('div');
    row.className = 'msg-row ' + (role === 'user' ? 'user' : 'bot');

    const avatar = document.createElement('div');
    avatar.className = 'avatar ' + (role === 'user' ? 'user' : 'bot');
    avatar.textContent = role === 'user' ? '你' : '珩';

    const wrap = document.createElement('div');
    wrap.className = 'msg-wrap ' + role;

    const bubble = document.createElement('div');
    bubble.className = 'msg';
    bubble.innerHTML = text.replace(/\\n/g, '<br>');

    const time = document.createElement('div');
    time.className = 'msg-time';
    time.textContent = timeStr();

    wrap.appendChild(bubble);
    wrap.appendChild(time);
    row.appendChild(avatar);
    row.appendChild(wrap);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function showTyping() {
    const existing = document.querySelector('.typing-row');
    if (existing) existing.remove();

    const row = document.createElement('div');
    row.className = 'typing-row';

    const avatar = document.createElement('div');
    avatar.className = 'avatar bot';
    avatar.textContent = '珩';

    const bubbles = document.createElement('div');
    bubbles.className = 'typing-bubbles';
    bubbles.innerHTML = '<span></span><span></span><span></span>';

    row.appendChild(avatar);
    row.appendChild(bubbles);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function setLoading(loading) {
    input.disabled = loading;
    sendBtn.disabled = loading;
    sendBtn.textContent = loading ? '思考中' : '发送 ▸';
    if (loading) showTyping();
}

// 欢迎消息
function showWelcome() {
    chatBox.innerHTML = '';
    const msg = `✦ 你好，我是 <strong>小珩</strong>。<br><br>
📚 <strong>知识库</strong> — 导入/搜索笔记、PDF<br>
🌐 <strong>网络搜索</strong> — 实时获取信息<br>
🧮 <strong>计算</strong> · 📖 <strong>文件操作</strong><br><br>
有什么可以帮你的？`;
    addMsg('assistant', msg);
}

async function send() {
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    addMsg('user', msg);
    setLoading(true);

    // 创建流式消息气泡（占位）
    const row = document.createElement('div');
    row.className = 'msg-row bot';
    row.innerHTML = `<div class="avatar bot">珩</div><div class="msg-wrap bot"><div class="msg" id="streamMsg"></div><div class="msg-time">${timeStr()}</div></div>`;
    const typingRow = document.querySelector('.typing-row');
    if (typingRow) typingRow.remove();
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
    const streamBubble = document.getElementById('streamMsg');

    let buffer = '';
    let renderIndex = 0;  // 已经渲染到的字符位置
    let renderTimer = null;  // setInterval 句柄
    const CHAR_PER_TICK = 2; // 每 tick 显示 2 个字符
    const TICK_MS = 30;      // tick 间隔（毫秒）

    // 真实时间延迟：每 TICK_MS 显示 CHAR_PER_TICK 个字，模拟打字机效果
    function startTyping() {
        if (renderTimer) return;
        renderTimer = setInterval(() => {
            if (renderIndex < buffer.length) {
                const target = Math.min(renderIndex + CHAR_PER_TICK, buffer.length);
                renderIndex = target;
                streamBubble.innerHTML = buffer.slice(0, renderIndex).replace(/\\n/g, '<br>');
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            // 如果 buffer 没有更多内容，timer 继续等待新 token 到来
        }, TICK_MS);
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function() {
        ws.send(JSON.stringify({message: msg}));
    };

    ws.onmessage = function(e) {
        const ev = JSON.parse(e.data);
        if (ev.type === 'text') {
            buffer += ev.content;
            startTyping();
        } else if (ev.type === 'reasoning') {
            // 可选显示推理过程
        } else if (ev.type === 'tool') {
            const toolNote = document.createElement('div');
            toolNote.style.cssText = 'font-size:11px;color:rgba(100,200,255,0.3);padding:2px 0;';
            toolNote.textContent = `🔧 ${ev.name}`;
            row.querySelector('.msg-wrap').insertBefore(toolNote, streamBubble);
        } else if (ev.type === 'done' || ev.type === 'error') {
            ws.close();
            // 停止打字机，立即显示全部内容
            if (renderTimer) {
                clearInterval(renderTimer);
                renderTimer = null;
            }
            renderIndex = buffer.length;
            streamBubble.innerHTML = (buffer || '（模型未返回内容）').replace(/\\n/g, '<br>');
            streamBubble.id = '';
            setLoading(false);
            input.focus();
        }
    };

    ws.onerror = function() {
        streamBubble.innerHTML = buffer || '❌ WebSocket 连接失败';
        streamBubble.id = '';
        setLoading(false);
        input.focus();
    };
}

async function loadHistory() {
    try {
        const res = await fetch('/api/history');
        const data = await res.json();
        if (data.history && data.history.length > 0) {
            chatBox.innerHTML = '';
            for (const msg of data.history) {
                addMsg(msg.role, msg.content);
            }
        } else {
            showWelcome();
        }
    } catch (e) {
        showWelcome();
    }
}

async function resetChat() {
    await fetch('/api/reset', {method: 'POST'});
    showWelcome();
    input.focus();
}

loadHistory();

// ── 图片上传/拍照 ──
async function uploadImage(input) {
    const file = input.files[0];
    if (!file) return;

    // 显示上传中
    addMsg('user', '📸 正在上传图片...');
    setLoading(true);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/upload-image', { method: 'POST', body: formData });
        const data = await res.json();

        // 移除临时"上传中"消息
        const lastMsg = chatBox.lastElementChild;
        if (lastMsg) lastMsg.remove();

        // 显示图片缩略图
        const imgHtml = `<div style="margin-bottom:8px"><img src="${data.url}" style="max-width:100%;max-height:200px;border-radius:10px;border:1px solid rgba(100,100,255,0.15)"></div>`;

        // 判断 OCR 是否成功
        if (data.ocr && !data.ocr.startsWith('❌')) {
            addMsg('assistant', `${imgHtml}📖 <strong>图片文字已识别</strong><br><br>${data.ocr.replace(/\\n/g, '<br>')}<br><br>💡 你可以继续追问图片内容～`);
        } else {
            addMsg('assistant', `${imgHtml}${data.ocr}`);
        }
    } catch (e) {
        const lastMsg = chatBox.lastElementChild;
        if (lastMsg) lastMsg.remove();
        addMsg('error', '❌ 上传失败，请检查服务器');
    }

    // 重置文件输入，允许重复选同一张
    input.value = '';
    setLoading(false);
    document.getElementById('input').focus();
}

// ── 知识库管理侧栏 ────────────────────────

let kbCurrentDocId = null;  // 当前查看/编辑的文档 ID

function toggleKbPanel() {
    const panel = document.getElementById('kbPanel');
    const overlay = document.getElementById('kbOverlay');
    const showing = panel.classList.toggle('show');
    overlay.classList.toggle('show', showing);
    if (showing) {
        kbLoadList();
        kbBackToList();
    }
}

async function kbLoadList() {
    const listEl = document.getElementById('kbList');
    const statsEl = document.getElementById('kbStats');
    try {
        const res = await fetch('/api/kb/list');
        const data = await res.json();
        statsEl.textContent = `共 ${data.total} 篇文档`;
        kbRenderList(data.documents, '');
    } catch (e) {
        listEl.innerHTML = '<div class="kb-empty">❌ 加载失败</div>';
        statsEl.textContent = '加载失败';
    }
}

function kbRenderList(docs, query) {
    const listEl = document.getElementById('kbList');
    if (!docs || docs.length === 0) {
        listEl.innerHTML = '<div class="kb-empty">📚 知识库是空的<br><br>点"新建笔记"或"导入文件"开始添加</div>';
        return;
    }
    let html = '';
    for (const doc of docs) {
        const preview = (doc.content || '').slice(0, 80).replace(/\\n/g, ' ');
        const highlighted = query ? highlightText(doc.title, query) : escapeHtml(doc.title);
        html += `<div class="kb-list-item" onclick="kbShowDetail('${doc.id}')">
            <div class="kb-item-title">${highlighted}</div>
            <div class="kb-item-preview">${escapeHtml(preview)}</div>
        </div>`;
    }
    listEl.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function highlightText(text, query) {
    const escaped = escapeHtml(text);
    if (!query) return escaped;
    const words = query.split(/\s+/).filter(w => w.length > 0);
    let result = escaped;
    for (const word of words) {
        const re = new RegExp('(' + word.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
        result = result.replace(re, '<strong style="color:#8c8cff">$1</strong>');
    }
    return result;
}

async function kbSearchDocs(query) {
    query = query.trim();
    const listEl = document.getElementById('kbList');
    const statsEl = document.getElementById('kbStats');
    kbCurrentDocId = null;  // 搜索时回到列表

    if (!query) {
        kbLoadList();
        return;
    }

    try {
        const res = await fetch('/api/kb/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query, top_k: 50})
        });
        const data = await res.json();
        const items = data.results || [];
        statsEl.textContent = `找到 ${items.length} 条结果`;
        const docs = items.map(r => ({...r.doc, _score: r.score}));
        kbRenderResults(docs, query);
    } catch (e) {
        listEl.innerHTML = '<div class="kb-empty">❌ 搜索失败</div>';
    }
}

function kbRenderResults(docs, query) {
    const listEl = document.getElementById('kbList');
    if (!docs || docs.length === 0) {
        listEl.innerHTML = `<div class="kb-empty">🔍 未找到相关结果</div>`;
        return;
    }
    let html = '';
    for (const doc of docs) {
        const preview = (doc.content || '').slice(0, 80).replace(/\\n/g, ' ');
        const score = doc._score ? Math.round(doc._score * 100) : 0;
        html += `<div class="kb-list-item" onclick="kbShowDetail('${doc.id}')">
            <div class="kb-item-title">${highlightText(doc.title, query)} <span class="kb-item-score">${score}%</span></div>
            <div class="kb-item-preview">${highlightText(preview, query)}</div>
        </div>`;
    }
    listEl.innerHTML = html;
}

async function kbShowDetail(docId) {
    kbCurrentDocId = docId;
    try {
        const res = await fetch(`/api/kb/doc/${docId}`);
        const data = await res.json();
        if (data.error) {
            document.getElementById('kbList').innerHTML = `<div class="kb-empty">❌ ${data.error}</div>`;
            return;
        }
        const doc = data.doc;
        const detailEl = document.getElementById('kbDetail');
        const listEl = document.getElementById('kbList');
        const formEl = document.getElementById('kbEditForm');
        formEl.style.display = 'none';
        listEl.style.display = 'none';
        detailEl.style.display = 'flex';
        detailEl.innerHTML = `
            <button class="kb-back" onclick="kbBackToList()">← 返回列表</button>
            <div class="kb-detail-title">${escapeHtml(doc.title)}</div>
            <div class="kb-detail-source">📎 ${escapeHtml(doc.source)}</div>
            <div class="kb-detail-content">${escapeHtml(doc.content)}</div>
            <div class="kb-detail-actions">
                <button onclick="kbShowEditForm('${doc.id}')">✏️ 编辑</button>
                <button class="btn-del" onclick="kbDeleteDoc('${doc.id}')">🗑️ 删除</button>
            </div>
        `;
    } catch (e) {
        document.getElementById('kbList').innerHTML = '<div class="kb-empty">❌ 加载失败</div>';
    }
}

function kbBackToList() {
    document.getElementById('kbDetail').style.display = 'none';
    document.getElementById('kbEditForm').style.display = 'none';
    document.getElementById('kbList').style.display = '';
    const searchVal = document.getElementById('kbSearch').value.trim();
    if (searchVal) kbSearchDocs(searchVal);
}

function kbShowAddForm() {
    kbCurrentDocId = null;
    document.getElementById('kbDetail').style.display = 'none';
    document.getElementById('kbList').style.display = 'none';
    const formEl = document.getElementById('kbEditForm');
    formEl.style.display = 'flex';
    formEl.innerHTML = `
        <button class="kb-back" onclick="kbBackToList()">← 返回列表</button>
        <label>📌 标题</label>
        <input type="text" id="kbFormTitle" placeholder="输入标题...">
        <label>📝 内容</label>
        <textarea id="kbFormContent" placeholder="输入笔记内容..."></textarea>
        <div class="form-actions">
            <button class="btn-save" onclick="kbSaveAdd()">✅ 保存</button>
            <button class="btn-cancel" onclick="kbBackToList()">取消</button>
        </div>
    `;
    document.getElementById('kbFormTitle').focus();
}

function kbShowEditForm(docId) {
    kbCurrentDocId = docId;
    fetch(`/api/kb/doc/${docId}`).then(r => r.json()).then(data => {
        if (data.error) return;
        const doc = data.doc;
        document.getElementById('kbDetail').style.display = 'none';
        const formEl = document.getElementById('kbEditForm');
        formEl.style.display = 'flex';
        formEl.innerHTML = `
            <button class="kb-back" onclick="kbBackToList()">← 返回列表</button>
            <label>📌 标题</label>
            <input type="text" id="kbFormTitle" value="${escapeHtml(doc.title)}">
            <label>📝 内容</label>
            <textarea id="kbFormContent">${escapeHtml(doc.content)}</textarea>
            <div class="form-actions">
                <button class="btn-save" onclick="kbSaveEdit()">✅ 保存</button>
                <button class="btn-cancel" onclick="kbBackToList()">取消</button>
            </div>
        `;
        document.getElementById('kbFormTitle').focus();
    });
}

async function kbSaveAdd() {
    const title = document.getElementById('kbFormTitle').value.trim();
    const content = document.getElementById('kbFormContent').value.trim();
    if (!title) { alert('请输入标题'); return; }
    if (!content) { alert('请输入内容'); return; }
    try {
        const res = await fetch('/api/kb/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title, content})
        });
        const data = await res.json();
        if (data.success) {
            kbBackToList();
            kbLoadList();
        } else {
            alert('保存失败');
        }
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}

async function kbSaveEdit() {
    const title = document.getElementById('kbFormTitle').value.trim();
    const content = document.getElementById('kbFormContent').value.trim();
    if (!title) { alert('请输入标题'); return; }
    try {
        const res = await fetch(`/api/kb/edit/${kbCurrentDocId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title, content})
        });
        const data = await res.json();
        if (data.success) {
            kbBackToList();
            kbLoadList();
        }
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}

async function kbDeleteDoc(docId) {
    if (!confirm('确定要删除这篇文档吗？')) return;
    try {
        await fetch(`/api/kb/delete/${docId}`, {method: 'POST'});
        kbBackToList();
        kbLoadList();
    } catch (e) {
        alert('删除失败');
    }
}

async function kbUploadFile(input) {
    const files = input.files;
    if (!files || files.length === 0) return;

    const listEl = document.getElementById('kbList');
    listEl.innerHTML = '<div class="kb-empty">⏳ 正在导入文件...</div>';

    let results = [];
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/kb/upload', {method: 'POST', body: formData});
            const data = await res.json();
            results.push(data.message || '✅ 导入完成');
        } catch (e) {
            results.push(`❌ ${file.name}: ${e.message}`);
        }
    }
    input.value = '';
    kbLoadList();
    setTimeout(() => {
        listEl.innerHTML = `<div class="kb-empty">${results.join('<br>')}</div>`;
        setTimeout(kbLoadList, 2000);
    }, 100);
}

// 键盘 ESC 关闭侧栏
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        const panel = document.getElementById('kbPanel');
        if (panel.classList.contains('show')) toggleKbPanel();
    }
});

// 照片上传后自动刷新知识库列表（如果面板开着）
const origAddMsg = addMsg;
addMsg = function(role, text) {
    origAddMsg(role, text);
    if (role === 'assistant' && text.includes('图片文字已识别')) {
        const panel = document.getElementById('kbPanel');
        if (panel.classList.contains('show')) kbLoadList();
    }
};
</script>
</body>
</html>"""
