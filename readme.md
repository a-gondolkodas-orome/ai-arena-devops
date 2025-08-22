# AI Arena Devops

This script allows you and manage an AI Arena Kubernetes deployment on Vultr.


## Prerequisites

- Python 3.x
- Vultr API Key
- Helm

## Initial Setup

1. Create and activate a virtual environment:

```sh
python3 -m venv venv
source venv/bin/activate   # On Windows, use `venv\Scripts\activate`
```

2. Install the required Python packages:

```sh
pip install -r requirements.txt
```

3. Add Helm repos

```sh
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus https://prometheus-community.github.io/helm-charts
helm repo update
```

## Running the Script

Command Line Arguments

api_key: Your Vultr API key (required).
--name: Name of the Kubernetes cluster (default: "ai-arena").
--region: Region of the Kubernetes cluster (default: "ams" for Amsterdam).
--version: Version of the Kubernetes cluster (default: latest version).
Example Commands
List clusters and create a new one if "ai-arena" does not exist with the latest Kubernetes version:

sh
Copy code
python manage_clusters.py your_api_key
List clusters and create a new one with specific name, region, and version:

sh
Copy code
python manage_clusters.py your_api_key --name my-cluster --region fra --version v1.21.0
Subsequent Uses
Activate the virtual environment:

sh
Copy code
source venv/bin/activate   # On Windows, use `venv\Scripts\activate`
Run the script as shown in the examples above.

Deactivating the Virtual Environment
To deactivate the virtual environment after you are done, run:

sh
Copy code
deactivate