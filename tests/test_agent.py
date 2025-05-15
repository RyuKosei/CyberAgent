import time
from src.utils.logger import AgentLogger
from src.agent.base_agent import BaseAgent
import os
from pathlib import Path

def test_original_scenario():
    test_log_dir = "logs/test_runs/original_scenario" 
    logger = AgentLogger(log_dir=test_log_dir)
    
    # Test script's own initial log messages
    logger.log_info(f"=== 测试脚本开始: 原始场景 (日志目录: {Path(test_log_dir).resolve()}) ===")
    
    agent = None
    try:
        agent = BaseAgent(logger=logger, model_name="gpt-4o-mini")

        original_prompt = """找到 G:\\Workspace 下的所有文件名"""
        # original_prompt = """找到 G:\Workspace\CyberAgent目录下的一个叫做“target.py”的文件，并输出其所在的绝对路径。"""
        # original_prompt = """找到 G:\Workspace\CyberAgent目录下的一个叫做“target.py”的文件，运行他并告诉我输出的结果。"""
        # original_prompt = """在G:\Workspace\CyberAgent\zicheng目录下创建一个compare.py的脚本，并写入一个比大小的程序，通过程序判断并输出pi的平方与10中较小的那个数字。"""

        # test_agent.py 不再重复记录 initial input, BaseAgent.run() 会记录
        print(f"\n=== 测试场景：原始需求 ===")
        print(f"用户指令:\n{original_prompt}")

        # agent.run() 内部会记录其接收到的输入和最终的输出
        result = agent.run(original_prompt)
        
        # test_agent.py 记录从 agent.run() 收到的结果，用于确认测试脚本正确接收
        logger.log_info(f"测试脚本收到Agent的最终结果: {result}")
        print("\nAgent最终输出 (由测试脚本记录):\n", result)
        
        if "错误" in result or "Error" in result or "No such file or directory" in result:
            logger.log_warning(f"Agent的最终结果中包含潜在的错误或问题提示。")
        elif result.strip() == "命令执行成功，但没有输出。" or not result.strip() or result == "Agent未能生成最终输出。":
            logger.log_warning(f"Agent的最终结果为空或提示没有内容，请检查目标目录 '{target_dir_windows}' 状态或Agent的执行逻辑。")
        else:
            logger.log_info("Agent成功返回了输出内容。")

    except Exception as e:
        logger.log_error(f"测试脚本执行过程中发生未捕获的严重错误", exc_info=True)
        print(f"Error during test scenario in test_agent.py: {str(e)}")
    finally:
        if agent:
            logger.log_info("测试脚本准备关闭Agent资源...")
            agent.close()
            logger.log_info("测试脚本确认Agent资源已关闭。")
        print("\n" + "="*50)
        logger.log_info(f"=== 测试脚本结束: 原始场景 ===")

if __name__ == "__main__":
    test_original_scenario()