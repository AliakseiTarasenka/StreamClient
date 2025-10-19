# StreamClient
WebSocket client used for interactive communication sessions during livestream events.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Prerequisites](#prerequisites)
3. [Project Setup](#project-setup)
4. [Running the Application](#running-the-application)
5. [Running Tests](#running-tests)
6. [Contributing](#contributing)
6. [Diagram](#relationship-diagram)

---

## Getting Started
Follow the steps below to set up and run the FastAPI-based StreamClient project.

### Prerequisites
Make sure you have:

- Python **>= 3.12**
- [`uv`](https://github.com/astral-sh/uv) (modern Python package manager)

Install `uv` if you don’t have it:
```bash
    pip install uv
```

### Project Setup via pipenv
1. Clone the project repository:
    ```bash
    git clone https://github.com/AliakseiTarasenka/StreamClient.git
    ```

2. Navigate to the project directory:
    ```bash
    cd StreamClient/
    ```

3. Install the required dependencies:
- Creates a virtual environment if it doesn’t exist
- Installs dependencies listed in pyproject.toml
- Syncs the environment to match your project configuration
    ```bash
    uv sync
    ```
4. Activate the virtual environment:
    ```bash
    source .venv/bin/activate
    ```
   
### Running tests

1. Use Makefile to run test commands:
    ```bash
    make test
    ```

### Relationship Diagrams:

1.  Teams, Players, Divisions
    https://dbdiagram.io/d/68e68028d2b621e422e49c03