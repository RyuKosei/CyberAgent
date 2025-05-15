# CyberAgent

一个强大的命令行代理，可以通过持久化的 bash 会话执行和分析 bash 命令。该代理旨在帮助用户完成文件系统操作和命令执行任务。

## 前置要求

- Python 3.8 或更高版本
- Git Bash（Windows 用户需要）
- OpenAI API 密钥

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/CyberAgent.git
cd CyberAgent
```

2. 安装依赖：
```bash
pip install -e .
```

## 环境变量

需要设置以下环境变量：

```bash
# OpenAI API 配置
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=your_api_base_url_here  # 可选，用于自定义 API 端点

# 模型配置
MODEL_NAME=gpt-4o-mini  # 或您偏好的其他模型
```

您可以通过以下两种方式设置这些变量：

1. 在 shell 中导出：
```bash
export OPENAI_API_KEY=your_api_key_here
export OPENAI_API_BASE=your_api_base_url_here
export MODEL_NAME=gpt-4o-mini
```

2. 在项目根目录创建 `.env` 文件（该文件已被 git 忽略）：
```bash
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=your_api_base_url_here
MODEL_NAME=gpt-4o-mini
```

## Git Bash 配置（Windows 用户）

代理需要安装并正确配置 Git Bash。如果您使用 Windows：

1. 从 [git-scm.com](https://git-scm.com/download/win) 安装 Git for Windows
2. 代理会自动检测以下常见安装位置的 Git Bash：
   - `C:\Program Files\Git\bin\bash.exe`
   - `C:\Program Files (x86)\Git\bin\bash.exe`
   - `C:\Program Files\Git\usr\bin\bash.exe`

如果 Git Bash 安装在其他位置，您可以使用 `BASH_EXEC_PATH` 环境变量设置路径：
```bash
export BASH_EXEC_PATH="C:\path\to\your\bash.exe"
```

## 使用方法

### 设置

1. 首先，确保所有环境变量都正确设置
2. 以开发模式安装包：
```bash
pip install -e .
```

### 运行代理

1. 启动 FastAPI 服务器：
```bash
python main.py
```

2. 在另一个终端中运行测试代理：
```bash
python tests/test_agent.py
```

测试代理将执行预定义的一组命令来验证代理的功能。

## 项目结构

```
CyberAgent/
├── src/
│   ├── agent/
│   │   └── base_agent.py      # 核心代理实现
│   ├── tools/
│   │   └── system_tools.py    # 系统命令执行工具
│   └── utils/
│       └── logger.py          # 日志工具
├── tests/
│   ├── test_agent.py         # 代理测试用例
│   └── test_command_tool.py  # 命令工具测试用例
├── logs/                     # 日志文件目录
├── main.py                   # FastAPI 服务器入口点
└── setup.py                  # 包配置
```

## 日志记录

代理在以下目录中生成详细的日志：
- `logs/base_agent_runs/` - 基础代理执行日志
- `logs/api_agent_runs/` - API 代理执行日志
- `logs/test_runs/` - 测试执行日志

每个日志文件包含：
- 环境信息
- 命令执行详情
- 工具使用情况和结果
- 错误信息和调试信息

## 未来工作

1. Docker 容器集成
   - 添加与 Docker 容器交互的支持
   - 实现容器管理命令
   - 添加容器状态持久化

2. API URL 配置
   - 添加在不同 API 端点之间切换的支持
   - 实现 API 端点验证
   - 添加 API 故障的备用机制

## 非 Windows 支持

虽然代理主要在 Windows 上测试，但它也包含对其他操作系统的支持：

- Linux：使用系统 bash（`/bin/bash` 或 `/usr/bin/bash`）
- macOS：支持通过 Homebrew 安装的 bash（`/usr/local/bin/bash`）

注意：非 Windows 平台的完整测试尚未完成。某些功能可能需要额外的配置或调整。

## 贡献

欢迎贡献！请随时提交 Pull Request。

## 许可证

本项目采用 MIT 许可证 - 详见 LICENSE 文件。 