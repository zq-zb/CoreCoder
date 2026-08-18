# 01 · MCP 第一小步：连接 Server 并发现工具

这一阶段只回答一个问题：**CoreCoder 怎样知道一个外部 MCP Server 会做什么？**

## 四个角色

- **Host**：承载整个 Agent 的应用，这里是 CoreCoder。
- **Client**：Host 内负责连接某个 MCP Server 的组件，这里是 `mcp_client.py`。
- **Server**：对外提供工具、资源或提示词的独立程序。
- **Transport**：Client 和 Server 传递消息的方式；本阶段使用 `stdio`。

一个 Host 可以创建多个 Client，每个 Client 分别连接一个 Server。第一版只有一个
Client 和一个演示 Server，先把最短链路跑通。

## stdio 是什么

操作系统为普通命令行程序提供三条标准通道：

- stdin：程序读取输入；
- stdout：程序写出正常结果；
- stderr：程序写出日志和错误。

在 stdio MCP 中，CoreCoder 把 Server 当作子进程启动，然后通过 stdin/stdout 交换
JSON-RPC 消息。因此 Server 不能随意向 stdout 打印调试文字，否则会污染协议消息；
需要调试时应该使用写入 stderr 的日志。

## 一次工具发现发生了什么

```text
CoreCoder                 MCP Server
    |                           |
    |---- initialize ---------->|
    |<--- Server 信息/能力 ------|
    |---- tools/list ---------->|
    |<--- 工具名称/描述/Schema ---|
    |                           |
```

`initialize` 是握手：双方确认协议版本和能力。`tools/list` 才是真正询问“你有哪些工具”。
官方 SDK 把这些 JSON-RPC 细节封装在 `Client` 和 `list_tools()` 里。

## 如何运行

安装项目依赖后，在仓库根目录执行：

```powershell
python -m corecoder.mcp_client python examples/mcp_demo_server.py
```

这里第一个 `python` 运行客户端；参数位置的第二个 `python` 表示用 Python 启动
Server。客户端会把第二个 `python` 解析成当前虚拟环境的解释器，避免 Client 和
Server 意外使用两套不同的依赖环境。

预期可以看到 `add` 工具及其参数 JSON Schema。这个阶段还不会真正调用 `add`，也不会
把它交给大模型；下一阶段才会实现 MCP Tool 到 CoreCoder `Tool` 接口的适配。
