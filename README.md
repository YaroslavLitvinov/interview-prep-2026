docker build -f Dockerfile.agent --build-arg DEBUG=1 -t autopilot-ws-prep .

# install claude so it goes to mounted .credentials folder
``` bash
IMAGE_TAG=autopilot-ws-prep PROJECT_ROOT=/home/yaroslav/git/clockwork-pilot/articles DOCKER_FILES=/home/yaroslav/git/clockwork-pilot/articles/docker-files PROXY_WRAPPER_CONFIG=  ~/git/clockwork-pilot/autopilot-ws/run-docker-workspace.sh "curl -fsSL https://claude.ai/install.sh | bash"
```

# run agent dockerize environment
``` bash
IMAGE_TAG=autopilot-ws-prep PROJECT_ROOT=~/git/clockwork-pilot/interview-prep-2026/ DOCKER_FILES=~/git/clockwork-pilot/interview-prep-2026/docker-files PROXY_WRAPPER_CONFIG=  ~/git/clockwork-pilot/autopilot-ws/run-docker-workspace.sh
```

# run streamlit app, exposing port
``` bash
IMAGE_TAG=autopilot-ws-prep PROJECT_ROOT=~/git/clockwork-pilot/interview-prep-2026/ DOCKER_FILES=~/git/clockwork-pilot/interview-prep-2026/docker-files PROXY_WRAPPER_CONFIG= DOCKER_FLAGS="-p 8501:8501"  ~/git/clockwork-pilot/autopilot-ws/run-docker-workspace.sh "DEBUG=1 streamlit run /workspace/app/interview_prep_app.py"
```