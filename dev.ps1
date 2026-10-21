# Python Docker Development Environment Helper Script

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("build", "start", "stop", "shell", "logs", "clean", "restart", "jupyter", "test", "format")]
    [string]$Command
)

switch ($Command) {
    "build" {
        Write-Host "Building Python development environment..." -ForegroundColor Green
        docker-compose build --no-cache
    }
    "start" {
        Write-Host "Starting Python development environment..." -ForegroundColor Green
        docker-compose up -d
        Write-Host "Environment is running! Use 'dev.ps1 shell' to access the container." -ForegroundColor Yellow
    }
    "stop" {
        Write-Host "Stopping Python development environment..." -ForegroundColor Yellow
        docker-compose down
    }
    "shell" {
        Write-Host "Opening shell in Python container..." -ForegroundColor Green
        docker-compose exec python-dev /bin/bash
    }
    "logs" {
        Write-Host "Showing container logs..." -ForegroundColor Blue
        docker-compose logs -f python-dev
    }
    "clean" {
        Write-Host "Cleaning up Docker resources..." -ForegroundColor Red
        docker-compose down -v --remove-orphans
        docker system prune -f
    }
    "restart" {
        Write-Host "Restarting Python development environment..." -ForegroundColor Yellow
        docker-compose restart
    }
    "jupyter" {
        Write-Host "Starting Jupyter Lab..." -ForegroundColor Green
        docker-compose exec python-dev jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root
    }
    "test" {
        Write-Host "Running tests..." -ForegroundColor Green
        docker-compose exec python-dev pytest
    }
    "format" {
        Write-Host "Formatting code with Black..." -ForegroundColor Green
        docker-compose exec python-dev black .
    }
}

# Usage information
if ($Command -eq $null) {
    Write-Host @"
Python Docker Development Environment

Usage: .\dev.ps1 <command>

Commands:
  build    - Build the Docker image
  start    - Start the development environment
  stop     - Stop the development environment
  shell    - Open a shell in the container
  logs     - Show container logs
  clean    - Clean up Docker resources
  restart  - Restart the environment
  jupyter  - Start Jupyter Lab
  test     - Run pytest
  format   - Format code with Black

Examples:
  .\dev.ps1 build
  .\dev.ps1 start
  .\dev.ps1 shell
"@ -ForegroundColor Cyan
}
