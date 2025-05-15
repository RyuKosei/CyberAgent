# src/utils/logger.py
import logging
import os
from datetime import datetime
from pathlib import Path
import sys # 用于 log_environment

class AgentLogger:
    def __init__(self, log_dir: str = "logs/agent_runs"): # 更改默认目录层级
        # 创建日志目录
        self.log_dir = Path(log_dir)
        # self.log_dir.mkdir(parents=True, exist_ok=True) # Defer mkdir to when a file is made or ensure path is specific
        
        # 创建日志文件名（使用时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") # Added microseconds for uniqueness
        # Ensure the specific log file's directory exists
        self.log_file_path = self.log_dir / f"agent_{timestamp}.log"
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # 配置日志记录器
        self.logger = logging.getLogger(f"AgentLogger_{timestamp}") # Unique logger name to avoid conflicts
        self.logger.setLevel(logging.DEBUG)
        
        # 防止重复添加 handlers, 对于unique logger name, 这可能不是必须的，但良好实践
        if not self.logger.handlers:
            # 文件处理器
            file_handler = logging.FileHandler(self.log_file_path, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            
            # 控制台处理器
            console_handler = logging.StreamHandler(sys.stdout) # Explicitly use sys.stdout
            console_handler.setLevel(logging.INFO)
            
            # 设置日志格式
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s', # Added logger name to format
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            # 添加处理器
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
        
        self.logger.info(f"Logger initialized. Log file: {self.log_file_path.resolve()}")

    def log_environment(self):
        """记录环境信息"""
        self.logger.info("=== 环境信息 ===")
        self.logger.info(f"当前工作目录: {os.getcwd()}")
        self.logger.info(f"Python版本: {sys.version.split()[0]}") # Cleaner Python version
        self.logger.info(f"操作系统: {sys.platform}")
    
    def log_agent_init(self, model_name: str, tools: list):
        """记录Agent初始化信息"""
        self.logger.info("=== Agent初始化 ===")
        self.logger.info(f"模型名称: {model_name}")
        tool_descs = []
        for tool in tools:
            if hasattr(tool, 'name') and hasattr(tool, 'description'):
                tool_descs.append(f"- {tool.name}: {tool.description[:100]}...") # Log snippet of description
            elif hasattr(tool, 'name'):
                 tool_descs.append(f"- {tool.name}: (No description property)")
            else:
                 tool_descs.append(f"- {type(tool).__name__}: (No name or description property)")

        self.logger.info(f"可用工具:\n" + "\n".join(tool_descs))
    
    def log_input(self, input_text: str):
        """记录用户输入"""
        self.logger.info("=== 用户输入 ===")
        self.logger.info(f"输入内容: {input_text}")
    
    def log_agent_thought(self, thought: str):
        """记录Agent的思考过程 (Langchain Callback Handler 会更细致地调用这些)"""
        # 在Langchain的回调中，通常我们会更具体地记录LLM的prompt, action等
        # 这个方法可以作为通用的思考记录点
        self.logger.debug(f"Agent Thought/Log: {thought}") # 保持为DEBUG，因为可能很冗长
    
    def log_llm_prompt(self, prompt: str):
        """记录发送给LLM的提示"""
        self.logger.debug(f"LLM Prompt: \n{prompt}")

    def log_llm_response(self, response: str):
        """记录LLM的响应"""
        self.logger.debug(f"LLM Response: \n{response}")

    def log_tool_use(self, tool_name: str, tool_input: any): # tool_input can be str or dict
        """记录工具使用情况"""
        input_str = str(tool_input)
        if isinstance(tool_input, dict):
            try:
                import json
                input_str = json.dumps(tool_input, ensure_ascii=False, indent=2)
            except TypeError: # Not all dicts are JSON serializable directly
                pass

        self.logger.info(f"Tool Used: {tool_name}")
        self.logger.debug(f"Tool Input: {input_str}") # Input can be verbose, so DEBUG
    
    def log_tool_result(self, tool_name: str, result: str):
        """记录工具执行结果 (Observation)"""
        self.logger.info(f"Tool Result (Observation) for {tool_name}:")
        self.logger.debug(f"{result}") # Result can be verbose, so DEBUG

    def log_output(self, output: str):
        """记录最终输出"""
        self.logger.info("=== 最终输出 ===")
        self.logger.info(f"输出内容: {output}")
    
    def log_error(self, error: str, exc_info: bool = False): # 添加 exc_info 参数
        """记录错误信息"""
        self.logger.error(f"ERROR: {error}", exc_info=exc_info)

    def log_warning(self, warning: str, exc_info: bool = False):
        """记录警告信息"""
        self.logger.warning(f"WARNING: {warning}", exc_info=exc_info)

    def log_debug(self, message: str): # 通用debug方法
        self.logger.debug(message)

    def log_info(self, message: str): # 通用info方法
        self.logger.info(message)