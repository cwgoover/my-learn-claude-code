#!/usr/bin/env python3
"""
s01_agent_loop.py - The Agent Loop

The entire secret of an AI coding agent in one pattern:

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Production agents layer
policy, hooks, and lifecycle controls on top.
"""

import os
import subprocess

# ── 依赖说明 ──────────────────────────────────────────────────
# anthropic  — Anthropic 官方 Python SDK，用于调用 Claude API
# dotenv     — 从 .env 文件加载环境变量，避免把密钥写死在代码里
from anthropic import Anthropic
from dotenv import load_dotenv

# ── 环境初始化 ────────────────────────────────────────────────
# load_dotenv() 会读取项目根目录下的 .env 文件，把里面的键值对注入 os.environ
# override=True 表示 .env 中的值会覆盖已存在的同名环境变量
load_dotenv(override=True)

# 语法技巧: os.getenv("KEY") 返回 str 或 None（key 不存在时）
#           os.environ["KEY"]  返回 str 或抛出 KeyError（key 不存在时）
#           前者适合"可选配置"，后者适合"必填配置"——缺了就应该立刻报错

# 如果用户配置了自定义 base_url（比如用兼容 API 的第三方服务），
# 就移除 ANTHROPIC_AUTH_TOKEN，避免 SDK 用错误的认证方式
if os.getenv("ANTHROPIC_BASE_URL"):
    # dict.pop(key, default) — key 不存在时返回 default 而不报错
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 创建 Anthropic 客户端实例
# base_url=None 时 SDK 使用默认的 Anthropic API 地址
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

# MODEL_ID 是必填项 —— 用 os.environ[] 而非 os.getenv()，缺失时直接报 KeyError
MODEL = os.environ["MODEL_ID"]

# ── 系统提示词 ────────────────────────────────────────────────
# system prompt 告诉模型它的角色和行为准则
# f-string 中嵌入 os.getcwd() 让模型知道当前工作目录
# "Act, don't explain" — 引导模型直接执行而不是长篇解释
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ── 工具定义 ──────────────────────────────────────────────────
# TOOLS 是一个列表，每个元素描述一个可供模型调用的工具
# 这里只定义了一个工具：bash（运行 shell 命令）
#
# 格式遵循 Anthropic Tool Use API:
#   name         — 工具名称，模型会在 response 中引用这个名字
#   description  — 告诉模型这个工具能做什么（模型据此决定何时调用）
#   input_schema — JSON Schema，定义工具接受的参数结构，是告诉 LLM "调用这个工具时，参数长什么样" 的一份契约。
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",  # 参数整体是一个 JSON对象（字典）
        "properties":  # 这个对象里有哪些字段：
          {
              "command": {"type": "string"} # command字段，类型是字符串
          },
        "required": ["command"], # command 是必填的
    },
}]

"""
input_schema 的意思等价于：
 def bash(command: str) -> str:    # 接受一个必填的 string 参数 command
 ...

实际效果： LLM 看到这个 schema 后，如果决定调用 bash 工具，就会生成符合格式的
  JSON:
 {"command": "ls -la"}

如果工具有多个参数, schema 就会更丰富，比如：

  "input_schema": {
      "type": "object",
      "properties": {
          "path":    {"type": "string", "description": "文件路径"},
          "content": {"type": "string", "description": "写入内容"},
      },
      "required": ["path", "content"],
  }

description 字段不是给你看的，是给 LLM
  看的——帮助它理解每个参数的用途，从而生成正确的调用参数。
"""


# ── 工具实现 ──────────────────────────────────────────────────
def run_bash(command: str) -> str:
    """执行一条 shell 命令并返回输出。

    安全措施:
    1. 危险命令黑名单 — 拦截 rm -rf / 等破坏性操作
    2. 超时限制 120 秒 — 防止命令无限挂起
    3. 输出截断 50000 字符 — 避免巨量输出撑爆上下文
    """
    # any() — 只要 dangerous 列表中有一个子串出现在 command 里就返回 True
    # 这是一种简单但不完美的安全检查（生产环境需要更严格的沙箱）
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # subprocess.run() — Python 执行外部命令的标准方式
        #   shell=True     : 通过 /bin/sh 解析命令字符串（支持管道、重定向等）
        #   cwd            : 子进程的工作目录
        #   capture_output : 捕获 stdout 和 stderr（等价于 stdout=PIPE, stderr=PIPE）
        #   text=True      : 将输出解码为 str（否则是 bytes）
        #   timeout        : 超时秒数，超时会抛出 TimeoutExpired
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        # 合并 stdout 和 stderr，去除首尾空白
        out = (r.stdout + r.stderr).strip()
        # 切片截断: out[:50000] — 最多保留前 50000 个字符
        # 这里最实用的特性：不会越界报错。 如果 out 只有 100 个字符，out[:50000] 就返回全部 100 个字符，不会抛异常。这比手动检查长度再截断简洁得多
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


# ── 核心: Agent 循环 ─────────────────────────────────────────
# 这是整个文件最重要的函数——所有 AI 编程代理的心脏都是这个 while 循环
def agent_loop(messages: list):
    """不断调用 LLM → 执行工具 → 把结果喂回去，直到 LLM 决定停下来。

    工作流程:
    1. 把 messages 发给 LLM, 得到 response
    2. 把 LLM 的回复追加到 messages (作为 assistant 消息)
    3. 检查 stop_reason:
       - "tool_use"  → LLM 想调用工具, 继续循环
       - "end_turn"  → LLM 认为任务完成, 退出循环
    4. 遍历 response.content 中所有 tool_use block, 逐一执行
    5. 把所有工具结果打包成一条 user 消息追加到 messages
    6. 回到第 1 步

    整个文件的灵魂就是 agent_loop 函数里的 while True 循环：       
    1. 发消息给 LLM → 2. LLM 回复里有 tool_use? → 3.       
    有就执行工具、把结果喂回去 → 4. 没有就退出
    """
    while True:
        # ① 调用 Claude API
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # ② 追加 assistant 回复到对话历史
        # response.content 是一个列表，可能包含 TextBlock 和 ToolUseBlock
        messages.append({"role": "assistant", "content": response.content})

        # ③ 判断是否继续循环
        # stop_reason == "tool_use" 意味着模型请求调用工具
        # stop_reason == "end_turn" 意味着模型已输出完毕
        if response.stop_reason != "tool_use":
            return

        # ④ 执行每个工具调用，收集结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # block.input 是模型传给工具的参数（字典）
                # block.id 是本次工具调用的唯一标识，结果必须带上它以便模型匹配
                print(f"\033[33m$ {block.input['command']}\033[0m")  # 黄色显示命令
                output = run_bash(block.input["command"])
                print(f"output=${output[:200]}")  # 只在终端预览前 200 字符
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})

        # ⑤ 把工具结果作为 user 消息追加
        # 关键洞察: 在 Anthropic API 中，tool_result 必须放在 role="user" 的消息里
        # 这样 LLM 下次循环就能"看到"工具的输出，并据此决定下一步
        messages.append({"role": "user", "content": results})


# ── 调试工具: 彩色打印对话历史（API 通信的真实 JSON 结构） ──────
import json

def _to_dict(obj):
    """把 SDK 对象（TextBlock, ToolUseBlock）转成与 API JSON 一致的纯字典。

    SDK 对象有 model_dump() 方法（Pydantic v2），调用它就能得到
    跟 API 请求/响应完全一致的字典结构。
    普通字典和字符串直接原样返回。
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    return obj

def print_history(history: list, start: int = 0):
    """用不同颜色打印 history[start:] 每条消息的真实 API JSON 结构。

    颜色方案:
      蓝色(34) — user 消息
      绿色(32) — assistant 消息
      紫色(35) — 分隔线
    """
    print("\n\033[35m" + "─" * 60)
    print(f"  📜 This turn ({len(history) - start} messages, index {start}~{len(history) - 1})")
    print("─" * 60 + "\033[0m")

    for i in range(start, len(history)):
        msg = history[i]
        role = msg["role"]
        color = "\033[34m" if role == "user" else "\033[32m"

        # 构造与 API 通信一致的纯 JSON 结构
        api_msg = {"role": role, "content": _to_dict(msg["content"])}
        raw = json.dumps(api_msg, indent=2, ensure_ascii=False)

        print(f"{color}[{i}]")
        for line in raw.split("\n"):
            print(f"  {line}")
        print(f"\033[0m")

    print("\033[35m" + "─" * 60 + "\033[0m\n")


# ── 入口: 交互式 REPL ────────────────────────────────────────
# REPL = Read-Eval-Print Loop（读取-执行-打印 循环）
if __name__ == "__main__":
    # __name__ == "__main__" 表示这个文件被直接运行（而非被 import）
    # 这是 Python 的标准入口守卫

    # history 在整个会话中累积对话，实现多轮对话
    history = []
    while True:
        try:
            # input() 显示提示符并等待用户输入
            # \033[36m ... \033[0m 是 ANSI 转义码，让提示符显示为青色
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D (EOFError) 或 Ctrl+C (KeyboardInterrupt) 时优雅退出
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        # 记录本轮开始前 history 的长度，用于之后只打印本轮新增的消息
        turn_start = len(history)

        # 把用户输入追加到 history，然后启动 agent 循环
        history.append({"role": "user", "content": query})
        agent_loop(history)

        # 打印 LLM 最终的文本回复
        # history[-1] 是最后一条 assistant 消息
        # response.content 可能包含 TextBlock（有 .text 属性）和 ToolUseBlock
        # 我们只打印文本部分
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)

        # 只打印本轮新增的消息（从 turn_start 开始）
        print_history(history, turn_start)
        print()
