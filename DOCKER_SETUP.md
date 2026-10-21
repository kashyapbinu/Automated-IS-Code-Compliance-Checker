# Python Docker Development Environment

A complete Python development environment using Docker with all the tools you need for modern Python development.

## What's Included

- **Python 3.11** with pip, setuptools, and wheel
- **Web Frameworks**: Flask, FastAPI with Uvicorn
- **Data Science**: NumPy, Pandas, Matplotlib, Seaborn, Jupyter
- **Testing**: pytest, coverage, Black formatter, Flake8 linter, mypy
- **Utilities**: requests, python-dotenv, click, PyYAML
- **Database**: SQLAlchemy, psycopg2
- **Development tools**: pre-commit, IPython

## Quick Start

### 1. Build the Environment
```powershell
.\dev.ps1 build
```

### 2. Start the Environment
```powershell
.\dev.ps1 start
```

### 3. Access the Python Shell
```powershell
.\dev.ps1 shell
```

## Available Commands

| Command | Description |
|---------|-------------|
| `.\dev.ps1 build` | Build the Docker image |
| `.\dev.ps1 start` | Start the development environment |
| `.\dev.ps1 stop` | Stop the development environment |
| `.\dev.ps1 shell` | Open a shell in the container |
| `.\dev.ps1 logs` | Show container logs |
| `.\dev.ps1 clean` | Clean up Docker resources |
| `.\dev.ps1 restart` | Restart the environment |
| `.\dev.ps1 jupyter` | Start Jupyter Lab (access at http://localhost:8888) |
| `.\dev.ps1 test` | Run pytest |
| `.\dev.ps1 format` | Format code with Black |

## Ports

The following ports are exposed:
- **5000**: Flask development server
- **8000**: General web server (FastAPI, etc.)
- **8888**: Jupyter Lab

## File Structure

```
.
├── Dockerfile          # Docker image definition
├── docker-compose.yml  # Docker Compose configuration
├── requirements.txt    # Python dependencies
├── .dockerignore      # Files to exclude from Docker context
├── dev.ps1            # Helper script for development
└── DOCKER_SETUP.md    # This file
```

## Development Workflow

1. **Start the environment**: `.\dev.ps1 start`
2. **Open a shell**: `.\dev.ps1 shell`
3. **Write your Python code** in the current directory (it's mounted to `/app` in the container)
4. **Run your code**: `python your_script.py`
5. **Run tests**: `pytest` or `.\dev.ps1 test`
6. **Format code**: `black .` or `.\dev.ps1 format`

## Adding New Dependencies

1. Add the package to `requirements.txt`
2. Rebuild the image: `.\dev.ps1 build`
3. Restart the environment: `.\dev.ps1 restart`

## Jupyter Lab

To use Jupyter Lab:
1. Start Jupyter: `.\dev.ps1 jupyter`
2. Open your browser to `http://localhost:8888`
3. Use the token shown in the terminal output

## Tips

- All files in the current directory are automatically synced with the container
- Installed packages persist between container restarts (thanks to Docker volumes)
- Use `.\dev.ps1 clean` to completely reset the environment if needed
- The container runs as a non-root user for security

## Troubleshooting

**Container won't start**: Check if ports 5000, 8000, or 8888 are already in use
**Permission errors**: Make sure Docker Desktop is running
**Build fails**: Try `.\dev.ps1 clean` then `.\dev.ps1 build`
