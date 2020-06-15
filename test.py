import os
import base64

print("PYTHON FTW!")
for s in ('IMAGE_REPO', 'GKE_DOCKER_REGISTRY', 'GKE_PROJECT_ID'):
    print(base64.b64encode(os.environ[s].encode('utf-8')))
