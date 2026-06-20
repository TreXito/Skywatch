from setuptools import setup, find_packages

setup(
    name="skywatch",
    version="1.0.0",
    description="Self-hostable live flight tracker with Discord alerts",
    packages=find_packages(include=["backend", "backend.*"]),
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.115",
        "uvicorn[standard]>=0.34",
        "httpx>=0.28",
        "pydantic>=2.10",
        "PyYAML>=6.0",
        "aiosqlite>=0.20",
        "python-multipart>=0.0.20",
    ],
    entry_points={"console_scripts": ["skywatch=backend.main:main"]},
)
