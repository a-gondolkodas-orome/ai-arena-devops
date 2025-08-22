import os
import requests
import json
import time
import base64


class VultrAPIError(Exception):
    """Custom exception for Vultr API errors."""
    pass


class VultrAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.vultr.com/v2"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def make_request(self, method, endpoint, payload=None):
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, data=json.dumps(payload) if payload else None)
        if response.status_code in [200, 201, 202, 204]:
            return response.json() if response.content else None
        else:
            error_message = response.json().get('error', 'Unknown error')
            raise VultrAPIError(
                f"Failed to {method} {endpoint}. Status code: {response.status_code}\nError: {error_message}")

    def list_kubernetes_clusters(self):
        return self.make_request('GET', '/kubernetes/clusters')['vke_clusters']

    def get_latest_kubernetes_version(self):
        versions = self.make_request('GET', '/kubernetes/versions')['versions']
        if not versions:
            raise VultrAPIError("No Kubernetes versions found.")
        return versions[0]

    def create_kubernetes_cluster(self, name, region, version, node_pools):
        payload = {
            "region": region,
            "version": version,
            "label": name,
            "node_pools": node_pools
        }
        return self.make_request('POST', '/kubernetes/clusters', payload)['vke_cluster']

    def delete_kubernetes_cluster(self, cluster_id):
        self.make_request('DELETE', f'/kubernetes/clusters/{cluster_id}')

    def list_node_pool_plans(self):
        return self.make_request('GET', '/plans')['plans']

    def list_block_storages(self):
        return self.make_request('GET', '/blocks')['blocks']

    def create_block_storage(self, label, region, size_gb, block_type):
        payload = {
            "label": label,
            "region": region,
            "size_gb": size_gb,
            "type": block_type
        }
        return self.make_request('POST', '/blocks', payload)['block']

    def wait_for_cluster_ready(self, cluster_id):
        first_check = True
        while True:
            clusters = self.list_kubernetes_clusters()
            cluster = next((cluster for cluster in clusters if cluster['id'] == cluster_id), None)
            if cluster and cluster['status'] == 'active':
                print(("" if first_check else "\n") + f'Cluster "{cluster_id}" is ready.')
                return not first_check
            print(f'Waiting for cluster "{cluster_id}" to be ready...' if first_check else '.', end='', flush=True)
            first_check = False
            time.sleep(10)

    def wait_for_block_storage_ready(self, block_id):
        first_check = True
        while True:
            blocks = self.list_block_storages()
            block = next((block for block in blocks if block['id'] == block_id), None)
            if block and block['status'] == 'active':
                print(("" if first_check else "\n") + f'Block storage "{block_id}" is ready.')
                break
            print(f'Waiting for block storage "{block_id}" to be ready...' if first_check else '.', end='', flush=True)
            first_check = False
            time.sleep(10)

    def get_kubernetes_kubeconfig(self, cluster_id, save_path):
        endpoint = f"/kubernetes/clusters/{cluster_id}/config"
        first_check = True
        while True:
            try:
                kubeconfig_base64 = self.make_request('GET', endpoint)['kube_config']
                print(("" if first_check else "\n") + "Kubeconfig downloaded.")
                break
            except ConnectionRefusedError as e:
                print("Waiting for the cluster config to be ready..." if first_check else '.', end='', flush=True)
                first_check = False
                time.sleep(10)

        kubeconfig = base64.b64decode(kubeconfig_base64).decode('utf-8')
        if save_path:
            with open(save_path, 'w') as f:
                f.write(kubeconfig)
            os.chmod(save_path, 0o600)
        return kubeconfig
