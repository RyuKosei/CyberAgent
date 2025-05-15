from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.agent.base_agent import BaseAgent
# from src.tools.system_tools import CommandTool # CommandTool is used internally by BaseAgent
from src.utils.logger import AgentLogger # Import if you want to create a specific logger for the app's agent
import uvicorn
import logging as fastapi_logging # Alias to avoid confusion with AgentLogger's self.logger
from pathlib import Path

# Configure basic logging for FastAPI/Uvicorn itself
fastapi_logging.basicConfig(level=fastapi_logging.INFO)
app_logger = fastapi_logging.getLogger("FastAPIApp")


app = FastAPI(title="Persistent Bash Agent API")

# Global Agent instance
# BaseAgent will initialize its own AgentLogger as per its __init__ default
# (e.g., logs/base_agent_runs/agent_<timestamp>.log)
# Or, create a specific logger for the agent used by the API:
api_agent_logger = AgentLogger(log_dir="logs/api_agent_runs")
agent_instance: BaseAgent = None

@app.on_event("startup")
async def startup_event():
    global agent_instance
    app_logger.info("FastAPI application startup...")
    try:
        # Pass the specific logger to the agent instance for the API
        agent_instance = BaseAgent(logger=api_agent_logger, model_name="gpt-4o-mini")
        app_logger.info("Global BaseAgent for API initialized successfully.")
    except Exception as e:
        app_logger.error(f"Failed to initialize global BaseAgent for API: {e}", exc_info=True)
        agent_instance = None # Ensure it's None if initialization fails

@app.on_event("shutdown")
def shutdown_event():
    global agent_instance
    app_logger.info("FastAPI application shutting down...")
    if agent_instance:
        app_logger.info("Closing API's BaseAgent resources...")
        agent_instance.close()
        app_logger.info("API's BaseAgent resources closed.")
    else:
        app_logger.info("API's BaseAgent was not initialized or already closed, no resources to close.")


class Query(BaseModel):
    text: str

@app.post("/execute")
async def execute_command(query: Query):
    global agent_instance
    if agent_instance is None:
        app_logger.error("API call to /execute failed because global agent is not initialized.")
        raise HTTPException(status_code=503, detail="Agent service is currently unavailable.")
    
    # Use the agent's own logger for this specific execution trace, if needed for correlation
    # agent_instance.logger.log_info(f"API /execute endpoint received query: {query.text}")
    app_logger.info(f"API /execute endpoint received query: {query.text}") # Or use app_logger

    try:
        result = agent_instance.run(query.text) # agent.run() will use its own logger (api_agent_logger)
        app_logger.info(f"API /execute endpoint agent returned: {result[:200]}...") # Log snippet
        return {"result": result}
    except Exception as e:
        # agent_instance.logger.log_error("Error during API /execute", exc_info=True)
        app_logger.error(f"Error during API /execute for query '{query.text}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred. Trace ID might be in server logs.")


if __name__ == "__main__":
    # Log directory for the API agent runs will be "logs/api_agent_runs"
    # Log directory for Uvicorn/FastAPI app logs are usually to console or configured separately
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")