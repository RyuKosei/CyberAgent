# src/tools/system_tools.py
from langchain.tools import BaseTool
from typing import Optional, Type, Any
from pydantic import BaseModel, Field, PrivateAttr # 确保 PrivateAttr 已导入
import subprocess
import os
import logging
import threading
import queue
import time
import sys # 用于 platform 和 expanduser

# 配置日志记录器 (这个logger是模块级别的，与AgentLogger分离)
logger = logging.getLogger(__name__)
# 基本配置，如果应用没有配置日志，这里会生效
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class CommandInput(BaseModel):
    command: str = Field(description="要执行的bash命令，例如：'cd /workspace' 或 'ls' 或 'cat file.txt'")

class CommandTool(BaseTool):
    """统一的bash命令执行工具，具有持久化会话功能。"""
    name: str = "command"
    description: str = """
    在持久的bash会话中执行bash命令并返回输出结果。
    会话状态（如当前目录）会在连续的命令之间保持。
    例如，如果你先执行 'cd /some/directory'，后续的 'ls' 命令会在此目录中执行。
    常用命令示例：
    - cd <path>: 切换目录。如果成功，会返回新的当前目录。
    - ls: 列出当前目录内容。
    - pwd: 显示当前工作目录。
    - mkdir <name>: 创建目录。
    - cat <file>: 查看文件内容。
    - echo <text>: 回显文本。
    - terminate_session: 关闭并重置当前的bash会话。
    命令包括但不限于以上命令，Git Bash支持的指令都可以使用。
    注意：出于安全考虑，某些危险命令（如rm不带-i选项、mkfs等）将被禁止执行。
    """
    args_schema: Type[BaseModel] = CommandInput
    
    bash_process: Optional[subprocess.Popen] = None
    output_queue: Optional[queue.Queue] = None
    session_id: str = Field(default_factory=lambda: f"bash_session_{time.time_ns()}_{os.getpid()}")

    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock) # 使用 PrivateAttr

    def __init__(self, **data: Any):
        super().__init__(**data)
        logger.info(f"[{self.session_id}] Initializing CommandTool instance {id(self)}.")
        self._start_session()

    def _find_bash(self) -> Optional[str]:
        """查找Bash可执行文件路径"""
        env_bash = os.getenv("BASH_EXEC_PATH")
        if env_bash and os.path.exists(env_bash):
            logger.info(f"[{self.session_id}] Using BASH_EXEC_PATH: {env_bash}")
            return env_bash

        bash_paths = []
        if sys.platform == "win32": # Windows
            bash_paths = [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe", # Git for Windows v2.x
                r"C:\Windows\System32\bash.exe", # WSL1 bash.exe (if path configured)
                # Consider searching user's PATH for bash.exe
            ]
            # Attempt to find bash via 'where' command if available
            try:
                where_process = subprocess.run(['where', 'bash'], capture_output=True, text=True, check=False)
                if where_process.returncode == 0 and where_process.stdout:
                    # Prioritize Git Bash paths if found by 'where'
                    found_paths = where_process.stdout.strip().split('\n')
                    git_bash_paths = [p for p in found_paths if "Git\\bin\\bash.exe" in p or "Git\\usr\\bin\\bash.exe" in p]
                    if git_bash_paths:
                        for gb_path in git_bash_paths:
                            if gb_path not in bash_paths: bash_paths.insert(0, gb_path) # Prioritize
                    else: # Add other found bash paths
                        for p in found_paths:
                             if p not in bash_paths: bash_paths.append(p)

            except FileNotFoundError:
                logger.debug(f"[{self.session_id}] 'where' command not found on Windows.")

        else: # macOS, Linux, etc.
            bash_paths = [
                "/bin/bash",
                "/usr/bin/bash",
                "/usr/local/bin/bash", # Common on macOS if installed via Homebrew
            ]
             # Attempt to find bash via 'which' command
            try:
                which_process = subprocess.run(['which', 'bash'], capture_output=True, text=True, check=False)
                if which_process.returncode == 0 and which_process.stdout:
                    found_path = which_process.stdout.strip()
                    if found_path not in bash_paths:
                        bash_paths.insert(0, found_path) # Prioritize
            except FileNotFoundError:
                logger.debug(f"[{self.session_id}] 'which' command not found.")


        for path in bash_paths:
            path = path.strip() # Clean up path string
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                logger.info(f"[{self.session_id}] Found bash at: {path}")
                return path
        
        logger.warning(f"[{self.session_id}] No bash executable found in common paths or via where/which. Last resort: trying 'bash' directly (relying on PATH).")
        # As a last resort, try 'bash' directly, relying on it being in PATH.
        # This is less reliable as Popen might not find it if PATH isn't correctly inherited.
        # To check this, we can do a quick test.
        try:
            test_proc = subprocess.run(['bash', '--version'], capture_output=True, timeout=2)
            if test_proc.returncode == 0:
                logger.info(f"[{self.session_id}] Successfully found 'bash' via system PATH.")
                return 'bash'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.error(f"[{self.session_id}] 'bash' not found in system PATH or test failed.")

        return None


    def _start_session(self):
        """启动持久的bash会话"""
        with self._lock:
            if self.bash_process and self.bash_process.poll() is None:
                logger.info(f"[{self.session_id}] Bash session (PID: {self.bash_process.pid}) already running.")
                return

            bash_path = self._find_bash()
            if not bash_path:
                logger.error(f"[{self.session_id}] CRITICAL: Bash executable not found. CommandTool will not function.")
                self.bash_process = None
                return

            try:
                self.bash_process = subprocess.Popen(
                    [bash_path, "-s"], # -s: read commands from stdin
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                    cwd=os.path.expanduser("~") # Start in user's home directory
                )
                self.output_queue = queue.Queue()

                threading.Thread(target=self._read_output, args=(self.bash_process.stdout, self.output_queue, "STDOUT"), daemon=True).start()
                threading.Thread(target=self._read_output, args=(self.bash_process.stderr, self.output_queue, "STDERR"), daemon=True).start()
                
                logger.info(f"[{self.session_id}] Bash session started (PID: {self.bash_process.pid}) with: {bash_path}")
                # Send an initial 'echo' to ensure the shell is responsive and pipes are working.
                # This also helps in clearing any initial welcome messages from some shells.
                init_marker = f"__INIT_MARKER_{time.time_ns()}__"
                self.bash_process.stdin.write(f"echo {init_marker}\n")
                self.bash_process.stdin.flush()
                
                init_success = False
                init_timeout = 5 # seconds
                init_start_time = time.time()
                temp_output = []
                while time.time() - init_start_time < init_timeout:
                    try:
                        stream_name, line = self.output_queue.get(timeout=0.1)
                        if init_marker in line:
                            init_success = True
                            logger.info(f"[{self.session_id}] Bash session initialization check successful.")
                            break
                        temp_output.append(f"({stream_name}) {line.strip()}")
                    except queue.Empty:
                        continue
                if not init_success:
                    logger.warning(f"[{self.session_id}] Bash session initialization check timed out or marker not found. Output during init: {' '.join(temp_output)}")


            except Exception as e:
                logger.error(f"[{self.session_id}] Failed to start bash session: {e}", exc_info=True)
                self.bash_process = None

    def _read_output(self, pipe: Optional[Any], q: Optional[queue.Queue], stream_name: str):
        if pipe is None or q is None: # Should not happen if _start_session is correct
            logger.error(f"[{self.session_id}] _read_output called with None pipe or queue for {stream_name}.")
            return
        try:
            for line in iter(pipe.readline, ''):
                q.put((stream_name, line))
            logger.debug(f"[{self.session_id}] Pipe for {stream_name} has been closed.")
        except Exception as e:
            # This can happen if the process terminates abruptly.
            logger.warning(f"[{self.session_id}] Exception while reading {stream_name} pipe: {e}")
        finally:
            # pipe.close() is usually handled by Popen.terminate/kill or when process ends.
            # Explicitly closing here might be redundant or cause issues if Popen is still managing it.
            pass


    def _convert_windows_path_to_bash(self, path: str) -> str:
        """将Windows路径转换为Git Bash能够理解的路径格式 (e.g., C:\\Users -> /c/Users)."""
        if sys.platform != "win32":
            return path # No conversion needed on non-Windows systems
            
        path = path.strip('"\'')
        if not path: return ""

        # If already a bash-style path (e.g., /c/Users or //network/path)
        if path.startswith('/') or path.startswith('\\\\'): # WSL paths can also be like //wsl$/Ubuntu/home
            # Normalize backslashes in network paths or mixed paths
            return path.replace('\\', '/')

        # Check for drive letter (e.g., C:)
        if ':' in path:
            drive, rest_of_path = path.split(':', 1)
            drive = drive.lower()
            # Remove leading slashes from rest_of_path if any, then normalize
            rest_of_path = rest_of_path.lstrip('\\/').replace('\\', '/')
            return f"/{drive}/{rest_of_path}"
        
        # If no drive letter, assume it's a relative path or needs normalization
        return path.replace('\\', '/')

    def _execute_raw_command_in_session(self, command: str, timeout: int = 20) -> str:
        if not self.bash_process or self.bash_process.poll() is not None:
            logger.warning(f"[{self.session_id}] Bash session not running or terminated. Attempting to restart.")
            self.close(restarting=True) # Ensure current process is cleaned up
            self._start_session() # Attempt to restart
            if not self.bash_process or self.bash_process.poll() is not None:
                return "错误: Bash会话未能启动或重启，无法执行命令。"
        
        # Clear any stale output from the queue before sending a new command
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break

        # Use a very unique end marker for each command
        unique_end_marker = f"__END_OF_COMMAND_OUTPUT_{time.time_ns()}_{os.getpid()}__"
        # Ensure the command and marker are on separate lines if command might not produce newline
        command_to_send = f"{command}\necho {unique_end_marker}\n" 
        
        logger.debug(f"[{self.session_id}] Sending to bash (PID {self.bash_process.pid}): {command.strip()} ; echo END_MARKER")
        
        try:
            self.bash_process.stdin.write(command_to_send)
            self.bash_process.stdin.flush()
        except (OSError, ValueError) as e: # OSError if pipe is broken, ValueError if closed
            logger.error(f"[{self.session_id}] Error writing to bash stdin (pipe likely broken): {e}", exc_info=True)
            # Attempt to restart the session
            self.close(restarting=True)
            self._start_session()
            if self.bash_process and self.bash_process.poll() is None:
                try:
                    logger.info(f"[{self.session_id}] Retrying command after session restart.")
                    self.bash_process.stdin.write(command_to_send)
                    self.bash_process.stdin.flush()
                except Exception as e2:
                    return f"错误: 写入命令到bash失败，即使在重启会话后: {e2}"
            else:
                return f"错误: Bash会话在写入命令失败后未能重启: {e}"


        output_buffer = []
        stderr_buffer = []
        start_time = time.time()
        command_completed = False

        while time.time() - start_time < timeout:
            try:
                stream_name, line = self.output_queue.get(timeout=0.1) # Short timeout for responsiveness
                
                if unique_end_marker in line:
                    # Process any part of the line before the marker
                    line_content_before_marker = line.split(unique_end_marker, 1)[0]
                    if line_content_before_marker.strip():
                        if stream_name == "STDOUT":
                            output_buffer.append(line_content_before_marker)
                        else: # STDERR
                            stderr_buffer.append(line_content_before_marker)
                    command_completed = True
                    break 
                
                if stream_name == "STDOUT":
                    output_buffer.append(line)
                else: # STDERR
                    stderr_buffer.append(line)

            except queue.Empty:
                # Check if process died unexpectedly
                if self.bash_process.poll() is not None:
                    logger.error(f"[{self.session_id}] Bash process (PID {self.bash_process.pid}) terminated unexpectedly during command execution: '{command}'. Exit code: {self.bash_process.returncode}")
                    # Attempt restart for next command
                    self.close(restarting=True) # Mark for restart
                    # self._start_session() # This would be for immediate restart, better to let next _run call handle it.
                    return f"错误: Bash进程在执行命令时意外终止。标准输出: {''.join(output_buffer).strip()} 标准错误: {''.join(stderr_buffer).strip()}"
                continue # Continue waiting if process is alive and timeout not reached
            except Exception as e: # Should be rare if queue/pipe handling is robust
                logger.error(f"[{self.session_id}] Exception while reading output queue for command '{command}': {e}", exc_info=True)
                return f"错误: 读取命令输出时发生意外: {e}"

        if not command_completed:
            logger.error(f"[{self.session_id}] Command '{command.strip()}' execution timed out ({timeout}s).")
            # Attempt to interrupt the hanging command by sending Ctrl+C, then a new marker.
            try:
                logger.warning(f"[{self.session_id}] Attempting to interrupt hanging command with Ctrl+C.")
                self.bash_process.stdin.write("\x03") # Ctrl+C
                self.bash_process.stdin.write(f"echo {unique_end_marker}_timeout_recovery\n") # New marker
                self.bash_process.stdin.flush()
                # Try to read a bit more to see if it recovered
                recovery_start_time = time.time()
                while time.time() - recovery_start_time < 2: # Short recovery timeout
                    try:
                        stream_name, line = self.output_queue.get(timeout=0.1)
                        if f"{unique_end_marker}_timeout_recovery" in line:
                            logger.info(f"[{self.session_id}] Successfully recovered from timeout with Ctrl+C.")
                            break
                        if stream_name == "STDOUT": output_buffer.append(f"[TIMEOUT_RECOVERY_OUTPUT] {line}")
                        else: stderr_buffer.append(f"[TIMEOUT_RECOVERY_ERROR] {line}")
                    except queue.Empty:
                        pass
            except Exception as e_interrupt:
                logger.error(f"[{self.session_id}] Error sending Ctrl+C or recovery marker after timeout: {e_interrupt}")
            
            return f"错误: 命令执行超时 ({timeout}s)。捕获的标准输出: {''.join(output_buffer).strip()} 标准错误: {''.join(stderr_buffer).strip()}"

        stdout_result = "".join(output_buffer).strip()
        stderr_result = "".join(stderr_buffer).strip()

        if stderr_result:
            logger.warning(f"[{self.session_id}] Command '{command.strip()}' produced STDERR:\n{stderr_result}")
            if not stdout_result:
                return f"命令执行错误 (来自STDERR): {stderr_result}"
            return f"命令输出 (来自STDOUT):\n{stdout_result}\n命令错误 (来自STDERR):\n{stderr_result}"
        
        return stdout_result if stdout_result else "命令执行成功，但没有输出。"

    def _run(self, command: str) -> str:
        with self._lock: # Ensure only one command is processed at a time through the tool instance
            original_command = command # For logging
            logger.info(f"[{self.session_id}] Received command for _run: '{original_command.strip()}'")

            if command.strip() == "terminate_session":
                logger.info(f"[{self.session_id}] Received 'terminate_session' command.")
                self.close(restarting=True) # Close current session
                self._start_session()    # Start a new one
                if self.bash_process and self.bash_process.poll() is None:
                    return "Bash会话已成功终止并重启。"
                else:
                    return "错误：Bash会话未能成功重启。"

            # Security check for dangerous commands
            dangerous_keywords = ['rm ', 'mkfs', 'fdisk', 'dd', 'shutdown', 'reboot', 'mv ', '>', '|', '&&', ';'] # Expanded list
            # More specific checks for redirection or chaining if not intended
            # For simplicity, we'll focus on command starts
            command_lower_stripped = command.lower().strip()
            
            is_dangerous_command_type = False
            # Check for commands that can be destructive if not used carefully
            # This is a basic check and can be expanded.
            # For example, `rm` without `-i` or `--preserve-root` on `/`
            # `mv` can also be dangerous if moving critical files or overwriting
            dangerous_prefixes = ['rm ', 'mkfs', 'fdisk', 'dd', 'shutdown', 'reboot', 'mv ']
            if any(command_lower_stripped.startswith(dp) for dp in dangerous_prefixes):
                if command_lower_stripped.startswith('rm ') and ('-i' in command_lower_stripped or '--interactive' in command_lower_stripped):
                    pass # Allow rm with interactive flag
                elif command_lower_stripped.startswith('mv ') and ('-i' in command_lower_stripped or '--interactive' in command_lower_stripped):
                    pass # Allow mv with interactive flag
                else:
                    is_dangerous_command_type = True
            
            if is_dangerous_command_type:
                logger.warning(f"[{self.session_id}] Attempted DANGEROUS command: {original_command.strip()}")
                return f"错误：出于安全考虑，禁止执行可能危险的命令: {original_command.strip()}"
    
            result = self._execute_raw_command_in_session(original_command)
            
            logger.debug(f"[{self.session_id}] Command '{original_command.strip()}' final result for _run:\n{result}")
            return result
            
    def close(self, restarting: bool = False):
        with self._lock: # Ensure thread safety during close
            action_log = "Restarting: Closing" if restarting else "Closing"
            if self.bash_process and self.bash_process.poll() is None: # Check if process exists and is running
                pid = self.bash_process.pid
                logger.info(f"[{self.session_id}] {action_log} bash session (PID: {pid})...")
                try:
                    if self.bash_process.stdin and not self.bash_process.stdin.closed:
                        self.bash_process.stdin.write("exit\n") # Politely ask to exit
                        self.bash_process.stdin.flush()
                        self.bash_process.stdin.close() # Close stdin to signal no more input
                    
                    # Wait for process to terminate after exit command
                    self.bash_process.wait(timeout=2) # Should be quick
                    logger.info(f"[{self.session_id}] Bash session (PID: {pid}) exited gracefully (code: {self.bash_process.returncode}).")
                except (subprocess.TimeoutExpired, OSError, ValueError) as e_graceful: # OSError/ValueError if pipes already closed/broken
                    logger.warning(f"[{self.session_id}] Bash session (PID: {pid}) did not exit gracefully after 'exit' command (Error: {e_graceful}). Terminating forcefully.")
                    try:
                        self.bash_process.terminate() # SIGTERM
                        self.bash_process.wait(timeout=2)
                        logger.info(f"[{self.session_id}] Bash session (PID: {pid}) terminated (SIGTERM) (code: {self.bash_process.returncode}).")
                    except (subprocess.TimeoutExpired, OSError) as e_term:
                        logger.warning(f"[{self.session_id}] Bash session (PID: {pid}) did not respond to SIGTERM (Error: {e_term}). Killing (SIGKILL).")
                        self.bash_process.kill() # SIGKILL
                        try:
                            self.bash_process.wait(timeout=1) # Wait for kill to complete
                            logger.info(f"[{self.session_id}] Bash session (PID: {pid}) killed (SIGKILL) (code: {self.bash_process.returncode}).")
                        except (subprocess.TimeoutExpired, OSError) as e_kill: # OSError if already dead
                             logger.error(f"[{self.session_id}] Bash session (PID: {pid}) failed to die even after SIGKILL or was already dead (Error: {e_kill}). Final poll: {self.bash_process.poll()}")
                finally:
                    # Ensure stdout/stderr pipes are also closed if Popen didn't manage it.
                    # Usually, when the process terminates, its pipes are closed by the OS.
                    if self.bash_process.stdout and not self.bash_process.stdout.closed: self.bash_process.stdout.close()
                    if self.bash_process.stderr and not self.bash_process.stderr.closed: self.bash_process.stderr.close()
                    self.bash_process = None # Clear the process attribute
            else:
                logger.info(f"[{self.session_id}] Bash session was not running or already closed when close() was called.")
        return "Bash会话已关闭。" # Or "Bash session resources cleaned up."

    def __del__(self):
        logger.info(f"[{self.session_id}] CommandTool instance {id(self)} is being deleted. Ensuring bash session is closed.")
        self.close() # Call the instance's close method

    async def _arun(self, command: str) -> str:
        # This is a synchronous tool. For async, wrap _run in asyncio.to_thread
        # import asyncio
        # return await asyncio.to_thread(self._run, command=command)
        logger.warning(f"[{self.session_id}] _arun called but not implemented asynchronously. Using synchronous _run.")
        return self._run(command=command)