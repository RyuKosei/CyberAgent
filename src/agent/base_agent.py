from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from src.tools.system_tools import CommandTool
from src.utils.logger import AgentLogger # 使用你的AgentLogger
from langchain.callbacks.base import BaseCallbackHandler # 更改导入
from typing import Any, Dict, List, Union # 添加类型提示
import os
from dotenv import load_dotenv
import json

load_dotenv()

class LoggingCallbackHandler(BaseCallbackHandler):
    def __init__(self, logger: AgentLogger):
        self.logger = logger
        self.current_step_number = 0 # Renamed for clarity
    
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> None:
        self.current_step_number = 0 # Reset step number for a new chain
        self.logger.log_info("=== Agent任务链开始 ===")
        # The initial overall input is logged by BaseAgent.run().
        # This logs the specific input to the AgentExecutor chain.
        self.logger.log_info(f"任务链接收到输入: {inputs.get('input', inputs)}")
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        self.logger.log_info(f"--- [步骤 {self.current_step_number}] LLM思考开始 ---")
        for i, prompt_text in enumerate(prompts):
             self.logger.log_llm_prompt(f"发送给LLM的提示 {i}:\n{prompt_text}")
    
    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        # 从 response 对象中提取文本内容
        content = "未从LLM响应中找到文本内容。"
        if hasattr(response, 'generations') and response.generations:
            first_gen_list = response.generations[0]
            if first_gen_list:
                first_gen = first_gen_list[0]
                if hasattr(first_gen, 'text') and first_gen.text:
                    content = first_gen.text
                elif hasattr(first_gen, 'message') and hasattr(first_gen.message, 'content'):
                    content = first_gen.message.content
        elif hasattr(response, 'content'): # For simpler message objects
            content = response.content
        
        self.logger.log_llm_response(content)
        self.logger.log_info(f"--- [步骤 {self.current_step_number}] LLM思考结束 ---")


    def on_agent_action(self, action: Any, **kwargs: Any) -> None: # action is AgentAction
        self.logger.log_info(f"--- [步骤 {self.current_step_number}] Agent计划动作 ---")
        self.logger.log_tool_use(tool_name=action.tool, tool_input=action.tool_input)
        if hasattr(action, 'log') and action.log:
            # LLM的思考过程导致了这个动作，这部分内容比较详细，适合DEBUG级别
            self.logger.log_agent_thought(f"LLM决策过程 (导致此动作):\n{action.log.strip()}")
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        self.logger.log_debug(f"--- [步骤 {self.current_step_number}] 工具 '{serialized.get('name', 'UnknownTool')}' 开始执行，输入: {input_str} ---")

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        tool_name = kwargs.get('name', 'UnknownTool')
        self.logger.log_info(f"--- [步骤 {self.current_step_number}] Agent观察到工具结果 ---")
        self.logger.log_tool_result(tool_name=tool_name, result=output) # log_tool_result 内部会用INFO和DEBUG
        self.current_step_number += 1 # Increment step number AFTER a full action-observation cycle completes
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        self.logger.log_info("=== Agent任务链结束 ===")
        # This logs the raw output object of the chain, for debugging/completeness
        self.logger.log_debug(f"任务链原始输出: {outputs}") 
    
    def on_agent_finish(self, finish: Any, **kwargs: Any) -> None: # finish is AgentFinish
        self.logger.log_info(f"--- [步骤 {self.current_step_number -1 if self.current_step_number > 0 else 0}] Agent决策完成 ---") # Step counter might have incremented
        # This logs the raw return_values of the agent's decision to finish
        self.logger.log_debug(f"Agent完成决策的原始返回值: {finish.return_values}")
        if hasattr(finish, 'log') and finish.log:
             self.logger.log_agent_thought(f"LLM最终决策思考过程:\n{finish.log.strip()}")

    def on_chain_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        self.logger.log_error(f"任务链执行错误: {error}", exc_info=True)

    def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        self.logger.log_error(f"LLM调用错误: {error}", exc_info=True)

    def on_tool_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        self.logger.log_error(f"工具执行错误: {error}", exc_info=True)


class BaseAgent:
    def __init__(self, model_name: str = "gpt-3.5-turbo", logger: AgentLogger = None, log_dir: str = "logs/base_agent_runs"):
        if logger:
            self.logger = logger
        else:
            self.logger = AgentLogger(log_dir=log_dir)
        
        self.logger.log_environment()
        
        callbacks = [LoggingCallbackHandler(self.logger)]
        
        self.llm = ChatOpenAI(
            model_name=model_name, 
            temperature=0,
        )
        
        self.command_tool = CommandTool()
        self.tools = [self.command_tool]
        self.logger.log_agent_init(model_name, self.tools)
        
        prompt_template_str = """
        你是一个专业的命令行助手，专注于执行和分析bash命令。你的主要职责是帮助用户完成文件系统操作和命令执行任务。
        逐步思考并决定采取何种行动。你可以使用以下工具：

        {tools}

        请严格按照以下格式进行响应：

        Question: 用户提出的原始问题或任务。
        Thought: 你对当前情况的思考，以及你计划采取的行动。说明你为什么选择某个工具以及具体的输入。
        Action: 你要使用的工具的名称，必须是[{tool_names}]中的一个。
        Action Input: 提供给所选工具的输入。
        Observation: 工具执行后返回的结果。
        ... (这个 Thought/Action/Action Input/Observation 的循环可以重复N次)
        Thought: 我现在已经收集了足够的信息，可以回答用户的问题了。
        Final Answer: 对原始问题的最终、完整回答。

        重要提示：
        1.  在改变目录 (cd) 后，工具会返回新的路径或错误。请将此作为你的观察。
        2.  如果一个命令没有输出，工具通常会返回 "命令执行成功，但没有输出。"。
        3.  如果发生错误，错误信息会包含在观察中。仔细阅读错误信息以决定下一步。
        4.  在提供最终答案之前，确保你已经完成了所有必要的步骤来满足用户的请求。
        5.  你的操作环境为Git Bash，所以请注意指令的格式，即便用户指定了Windows下的路径，你也要分析并给出正确的指令。

        开始!

        Question: {input}
        {agent_scratchpad}
        """ # Note: User added point 5 to the prompt, which is good.
        self.prompt = ChatPromptTemplate.from_template(prompt_template_str)
        
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )
        
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True, 
            handle_parsing_errors="True", # Pass as string "True" or "False" or a custom function
            callbacks=callbacks,
            max_iterations=20,
        )
    
    def run(self, input_text: str) -> str:
        # 这是任务的总入口，记录一次用户最原始的指令
        self.logger.log_input(f"Agent接收到任务总指令: {input_text}")
        try:
            response = self.agent_executor.invoke({"input": input_text})
            output = response.get("output", "Agent未能生成最终输出。")
            # 这是Agent对整个任务的最终回答，是用户最关心的结果之一
            self.logger.log_output(f"Agent对任务的最终回答: {output}")
            return output
        except Exception as e:
            error_msg = f"Agent在执行任务 '{input_text[:50]}...' 时发生严重错误"
            self.logger.log_error(error_msg, exc_info=True)
            return f"{error_msg}: {str(e)}"
    
    def close(self):
        self.logger.log_info("BaseAgent close方法被调用，开始关闭内部工具...")
        if hasattr(self, 'command_tool') and self.command_tool:
            self.command_tool.close()
        self.logger.log_info("BaseAgent内部工具已关闭。")

    def __del__(self):
        self.close()