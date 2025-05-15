from setuptools import setup, find_packages

setup(
    name="cyber_agent",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "langchain>=0.1.0",
        "langchain-community>=0.0.10",
        "openai>=1.0.0",
        "python-dotenv>=0.19.0",
        "fastapi>=0.68.0",
        "uvicorn>=0.15.0",
        "pydantic>=1.8.0"
    ],
) 