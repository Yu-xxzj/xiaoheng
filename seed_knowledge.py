"""
📚 示例：给知识库添加一些笔记
运行: python3 seed_knowledge.py
"""
import sys, os, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_base import KnowledgeBase

kb = KnowledgeBase()

# 添加一些操作系统笔记
notes = [
    ("操作系统 - 进程状态",
     "进程有三种基本状态：就绪(Ready)、运行(Running)、阻塞(Blocked)。\n"
     "就绪→运行：进程调度\n"
     "运行→就绪：时间片用完\n"
     "运行→阻塞：等待I/O或事件\n"
     "阻塞→就绪：I/O完成\n\n"
     "创建状态和终止状态是辅助状态。"),

    ("操作系统 - 进程调度算法",
     "常见调度算法：\n"
     "1. FCFS（先来先服务）：非抢占，平均等待时间长\n"
     "2. SJF（短作业优先）：可证明最优平均等待时间，但难以预知执行时间\n"
     "3. 优先级调度：可能导致低优先级进程饥饿\n"
     "4. 时间片轮转(RR)：公平，响应快，时间片选择关键\n"
     "5. 多级反馈队列：MLFQ，综合多种算法优点\n\n"
     "现代操作系统一般用多级反馈队列。"),

    ("操作系统 - 死锁",
     "死锁的必要条件（四个必须同时满足）：\n"
     "1. 互斥：资源一次只能一个进程使用\n"
     "2. 请求与保持：进程已持有资源，又请求新资源\n"
     "3. 不可剥夺：资源不能被强行夺走\n"
     "4. 循环等待：存在进程资源的循环链\n\n"
     "处理方法：\n"
     "- 预防：破坏四个条件之一\n"
     "- 避免：银行家算法\n"
     "- 检测+恢复：检测到死锁后撤销或回滚进程"),

    ("操作系统 - 内存管理",
     "内存管理方式：\n"
     "1. 连续分配：固定分区、动态分区\n"
     "2. 分页：将逻辑地址空间分页，物理内存分块\n"
     "   逻辑地址 = 页号 + 页内偏移\n"
     "3. 分段：按逻辑功能分段\n"
     "4. 段页式：先分段，段内分页\n\n"
     "虚拟内存：允许程序运行大小超过物理内存\n"
     "页面置换算法：FIFO, LRU, Clock, 最佳置换算法"),

    ("Python - 列表推导式",
     "列表推导式是Python中创建列表的简洁方式：\n\n"
     "[表达式 for 变量 in 可迭代对象 if 条件]\n\n"
     "例子：\n"
     "squares = [x**2 for x in range(10)]\n"
     "evens = [x for x in range(20) if x % 2 == 0]\n"
     "pairs = [(x,y) for x in [1,2] for y in [3,4]]"),

    ("Python - 装饰器",
     "装饰器是一种高阶函数，用于在不修改原函数代码的情况下添加功能：\n\n"
     "def timer(func):\n"
     "    def wrapper(*args, **kwargs):\n"
     "        start = time.time()\n"
     "        result = func(*args, **kwargs)\n"
     "        print(f'{func.__name__} took {time.time()-start:.2f}s')\n"
     "        return result\n"
     "    return wrapper\n\n"
     "@timer\n"
     "def slow_function():\n"
     "    time.sleep(1)"),

    ("计算机网络 - TCP三次握手",
     "TCP建立连接需要三次握手：\n\n"
     "1. Client → Server: SYN=1, seq=x\n"
     "2. Server → Client: SYN=1, ACK=1, seq=y, ack=x+1\n"
     "3. Client → Server: SYN=0, ACK=1, seq=x+1, ack=y+1\n\n"
     "为什么是三次而不是两次？\n"
     "防止已失效的连接请求突然传到服务器，导致错误建立连接。\n\n"
     "TCP释放连接需要四次挥手。"),
]

for title, content in notes:
    print(kb.add_text(title, content))

print()
print("📚 知识库就绪！试试搜索 '进程调度'")
