import subprocess
import os
import sys
import time
import threading
import queue

class PersistentBashSession:
    def __init__(self, bash_exe_path=None):
        """
        Initializes a persistent bash session.
        Finds Git Bash if path is not provided.
        """
        if bash_exe_path:
            self.bash_path = bash_exe_path
        else:
            self.bash_path = self._find_git_bash()

        if not self.bash_path:
            raise FileNotFoundError("Git Bash executable not found. Please install Git for Windows or provide the correct path.")

        self.encoding = 'utf-8'
        self.process = None
        self.output_queue = queue.Queue()
        self.stdout_thread = None
        self._start_session()

    def _find_git_bash(self):
        """
        Finds the Git Bash executable in common locations.
        """
        common_paths = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\Users\{}\AppData\Local\Programs\Git\bin\bash.exe".format(os.getlogin()), # Common user-specific install
            r"C:\Git\bin\bash.exe" # Custom install location
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        # Check PATH environment variable
        try:
            path_output = subprocess.check_output(["where", "bash"], text=True, shell=True, stderr=subprocess.DEVNULL)
            paths_in_env = path_output.strip().split('\n')
            for p in paths_in_env:
                if p and "git" in p.lower() and "bash.exe" in p.lower() and os.path.exists(p.strip()):
                    return p.strip()
        except subprocess.CalledProcessError:
            pass # 'where bash' might not find it or 'where' command not available

        return None

    def _start_session(self):
        """
        Starts the bash process and the output reading thread.
        """
        try:
            # Start bash process
            # bufsize=1 for line buffering
            # stderr=subprocess.STDOUT merges stderr into stdout for simpler reading by one thread
            self.process = subprocess.Popen(
                [self.bash_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Merge stderr to stdout
                text=True,
                encoding=self.encoding,
                errors='replace',
                bufsize=1,  # Line buffered
                shell=False # Do not use shell=True with a list of args for security and clarity
            )

            # Start thread to read stdout
            self.stdout_thread = threading.Thread(target=self._enqueue_output, args=(self.process.stdout, self.output_queue))
            self.stdout_thread.daemon = True # Thread will exit when main program exits
            self.stdout_thread.start()
            print(f"Bash session started with PID: {self.process.pid}")

        except Exception as e:
            print(f"Error starting bash session: {e}")
            self.process = None # Ensure process is None if startup fails
            raise

    def _enqueue_output(self, pipe, q):
        """
        Reads lines from the pipe and puts them into the queue.
        Runs in a separate thread.
        """
        try:
            for line in iter(pipe.readline, ''):
                q.put(line)
        except ValueError: # Occurs if pipe is closed while readline is active
            pass
        except Exception as e:
            q.put(e) # Propagate other exceptions to the main thread via queue
        finally:
            pipe.close() # Ensure pipe is closed on thread exit

    def run_command(self, command, timeout=30):
        """
        Runs a command in the persistent bash session and returns its output and exit code.
        """
        if not self.process or self.process.poll() is not None:
            # Try to restart session if it died unexpectedly
            print("Bash process is not running. Attempting to restart...")
            try:
                self._start_session()
                if not self.process or self.process.poll() is not None: # Check again
                     return "Error: Bash process could not be started or is not running.", -1
            except Exception as e:
                return f"Error: Failed to restart bash process: {e}", -1


        # Generate unique markers for this command execution
        # Using time and random elements to ensure high uniqueness
        timestamp_marker = str(time.time_ns())
        command_output_end_signal = f"__CMD_OUTPUT_END__{timestamp_marker}"
        exit_code_signal_prefix = f"__EXIT_CODE__{timestamp_marker}:"
        command_processed_signal = f"__COMMAND_PROCESSED__{timestamp_marker}"

        # Construct the full command to be sent to bash
        # 1. Execute the user's command.
        # 2. Echo a small separator (like an empty line) to help with parsing later.
        # 3. Capture the exit code ($?).
        # 4. Echo the exit code signal.
        # 5. Echo the final processed signal.
        # Note: The initial `echo` helps ensure that if the command output doesn't end with a newline,
        # our signals still start on fresh lines.
        full_shell_command = (
            f"{command}\n"
            f"echo\n" 
            f"EXIT_CODE=$?\n"
            f"echo \"{exit_code_signal_prefix}$EXIT_CODE\"\n"
            f"echo \"{command_processed_signal}\"\n"
        )

        try:
            self.process.stdin.write(full_shell_command)
            self.process.stdin.flush()
        except (OSError, BrokenPipeError) as e:
            # This can happen if bash exited due to the command itself (e.g., user typed 'exit')
            # or if the process died for other reasons.
            print(f"Error writing to bash stdin (process might have exited): {e}")
            # Attempt to get any remaining output
            output_lines = []
            while not self.output_queue.empty():
                try:
                    line_content = self.output_queue.get_nowait()
                    if isinstance(line_content, str):
                        output_lines.append(line_content.rstrip('\r\n'))
                except queue.Empty:
                    break
            return "\n".join(output_lines), -1 # Indicate error or premature exit

        output_lines = []
        exit_code = None
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                print(f"Error: Timeout ({timeout}s) waiting for command markers for: '{command[:50]}...'")
                # Optionally, you might want to try and kill/restart the bash process here if it's truly stuck
                # For now, we return what we have and an error code.
                return "\n".join(output_lines) + "\n[TIMEOUT]", -1

            try:
                # Get line from queue with a short timeout to prevent blocking indefinitely
                # if the reading thread or bash process has an issue.
                line = self.output_queue.get(timeout=0.1)

                if isinstance(line, Exception): # An exception from the reader thread
                    print(f"Error from output reader thread: {line}")
                    return "\n".join(output_lines), -1 # Propagate error

                line = line.rstrip('\r\n') # Clean newlines

                if line == command_processed_signal:
                    break # All signals received, command processing is complete
                elif line.startswith(exit_code_signal_prefix):
                    exit_code_str = line[len(exit_code_signal_prefix):]
                    try:
                        exit_code = int(exit_code_str)
                    except ValueError:
                        print(f"Warning: Could not parse exit code from: '{line}'")
                        exit_code = -999 # Special error code for parsing failure
                elif line == command_output_end_signal : # Optional: if you had this signal earlier
                    pass # Just an intermediate signal, ignore for final output list
                else:
                    # This is part of the actual command output
                    # However, the `echo` we added after the user command will also be captured here.
                    # We need to be careful if the `echo` itself is meaningful output.
                    # The current logic collects all lines before the signals.
                    # The `echo` after the command is primarily to ensure subsequent signals are on new lines.
                    # If `command` was `echo -n "something"`, our `echo` ensures a newline before signals.
                    output_lines.append(line)

            except queue.Empty:
                # Queue is empty, means reader thread hasn't produced new output yet
                # or all output has been consumed.
                # Check if the process is still alive.
                if self.process.poll() is not None:
                    # Process terminated unexpectedly. Drain queue for any remaining output.
                    print(f"Error: Bash process terminated unexpectedly (exit code: {self.process.poll()}) while waiting for markers for command: '{command[:50]}...'")
                    while not self.output_queue.empty():
                        try:
                            rem_line = self.output_queue.get_nowait()
                            if isinstance(rem_line, str) and not rem_line.startswith("__EXIT_CODE__") and not rem_line.startswith("__COMMAND_PROCESSED__"):
                                output_lines.append(rem_line.rstrip('\r\n'))
                        except queue.Empty:
                            break
                    return "\n".join(output_lines), self.process.poll() if self.process.poll() is not None else -1
                # If process is alive, just continue waiting for output
                continue
            except Exception as e: # Catch other unexpected errors during queue processing
                print(f"Error processing output queue: {e}")
                return "\n".join(output_lines), -1 # Generic error


        # Filter out the blank line produced by our "echo" command if it's the last one before signals.
        # This is a bit heuristic. If the user command itself produces trailing blank lines, they'll be kept.
        # The main purpose of that 'echo' was to ensure signals are on new lines.
        if output_lines and output_lines[-1] == "":
            output_lines.pop()

        return "\n".join(output_lines), exit_code if exit_code is not None else -1 # Return -1 if exit code wasn't parsed

    def close(self):
        """
        Closes the bash session gracefully.
        """
        print("Closing bash session...")
        if self.process and self.process.poll() is None: # If process exists and is running
            try:
                self.process.stdin.write("exit\n")
                self.process.stdin.flush()
                self.process.stdin.close() # Close stdin to signal no more input
            except (OSError, ValueError, BrokenPipeError) as e: # stdin might already be closed
                print(f"Note: Error closing stdin (might be already closed): {e}")

            try:
                # Wait for process to terminate, with a timeout
                self.process.wait(timeout=5)
                print(f"Bash process exited with code: {self.process.returncode}")
            except subprocess.TimeoutExpired:
                print("Timeout waiting for bash to exit gracefully. Killing.")
                self.process.kill() # Force kill
                self.process.wait() # Ensure it's reaped
                print("Bash process killed.")
            except Exception as e:
                print(f"Exception during process wait/kill: {e}")

        # Wait for the stdout reader thread to finish
        if self.stdout_thread and self.stdout_thread.is_alive():
            # The thread should exit as its pipe will be closed when the process terminates.
            self.stdout_thread.join(timeout=2)
            if self.stdout_thread.is_alive():
                print("Warning: stdout reader thread did not exit cleanly.")

        # Clean up queue just in case
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break
        
        self.process = None
        print("Bash session closed.")

    # Context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def test_persistent_session():
    """
    Test basic command execution in a persistent Git Bash session.
    """
    try:
        with PersistentBashSession() as bash:
            commands = [
                "pwd",                            # Show current directory
                "ls -la",                         # List directory content
                "cd ..",
                "ls",   
            ]

            for cmd in commands:
                print(f"\n>>> Executing command: {cmd}")
                output, exit_code = bash.run_command(cmd, timeout=10) # 10 second timeout per command
                print(f"<<< Exit Code: {exit_code}")
                print(f"<<< Output:\n{output}")
                print("-" * 50)
                if exit_code == -1 and "process could not be started" in output : # Critical error
                    print("Aborting test due to bash process failure.")
                    break
                # Small delay for readability of tests, not strictly necessary
                time.sleep(0.1)
            
            # Test a command that might take longer than the default read timeout but less than command timeout
            print(f"\n>>> Executing command: sleep 3 && echo 'Done sleeping 3s'")
            output, exit_code = bash.run_command("sleep 3 && echo 'Done sleeping 3s'", timeout=5)
            print(f"<<< Exit Code: {exit_code}")
            print(f"<<< Output:\n{output}")
            print("-" * 50)


    except FileNotFoundError as e:
        print(e)
    except Exception as e:
        print(f"An unexpected error occurred during the test: {e}")

if __name__ == "__main__":
    test_persistent_session()