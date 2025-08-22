import argparse
import json
import subprocess
import time
from vultr_api import VultrAPI, VultrAPIError
import kubernetes
import base64
import yaml


def get_or_create_block_storage(api, region, label, size_gb):
    block = next((block for block in api.list_block_storages() if block['label'] == label), None)
    if block:
        print(f'Block storage "{label}" already exists with ID: {block["id"]}')
    else:
        print(f'Block storage "{label}" not found. Creating one...')
        block = api.create_block_storage(label, region, size_gb, 'high_perf')
        print(f'Created block storage "{label}" with ID: {block["id"]}')
    return block


def run_command_line_command(args, capture_output=False):
    print(' '.join(args))
    return subprocess.run(args, capture_output=capture_output, check=True)


def helm_install_ai_arena(kubeconfig_path, volume_handles):
    print('Checking if ai-arena is already installed...')
    result = run_command_line_command(
        ['helm', 'list', '--filter', '^ai-arena$', '--kubeconfig', kubeconfig_path, '-o', 'json'], True)

    installed_charts = json.loads(result.stdout)
    if any(chart['name'] == 'ai-arena' for chart in installed_charts):
        print('ai-arena is already installed, upgrading')
    else:
        print('Installing ai-arena...')
        run_command_line_command(
            ['helm', 'install', 'ai-arena', 'elastic/eck-operator-crds', '--kubeconfig',
             kubeconfig_path])
    run_command_line_command(
        ['helm', 'upgrade', 'ai-arena', 'helm/ai-arena', '-f', 'helm/ai-arena/values.yaml',
         '--set', f'mongodb.volumeHandle={volume_handles["mongodb"]}',
         '--set', f'elasticsearch.volumeHandle={volume_handles["elasticsearch"]}',
         '--set', f'prometheus.volumeHandle={volume_handles["prometheus"]}',
         '--set', f'grafana.volumeHandle={volume_handles["grafana"]}',
         '--kubeconfig', kubeconfig_path])


def get_or_create_secret(namespace, secret_name, secret_data):
    # Encode the password in base64
    encoded_secret_data = {key: base64.b64encode(value.encode('utf-8')).decode('utf-8') for [key, value] in
                           secret_data.items()}

    # Create the Kubernetes secret object
    secret = kubernetes.client.V1Secret(
        metadata=kubernetes.client.V1ObjectMeta(name=secret_name),
        data=encoded_secret_data
    )

    api = kubernetes.client.CoreV1Api()
    # Apply the secret to the specified namespace
    try:
        secret = api.read_namespaced_secret(namespace=namespace, name=secret_name)
        print(f"Secret '{secret_name}' found in namespace '{namespace}'.")
        return secret
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"Secret '{secret_name}' not found in namespace '{namespace}'. Creating it...")
            secret = api.create_namespaced_secret(namespace=namespace, body=secret)
            print(f"Secret '{secret_name}' created successfully in namespace '{namespace}'.")
            return secret
        else:
            raise e


def print_management_sites():
    pods = kubernetes.client.CoreV1Api().list_namespaced_pod(namespace="default",
                                                             label_selector="app=ai-arena-frontend")
    node = kubernetes.client.CoreV1Api().read_node(pods.items[0].spec.node_name) if len(pods.items) == 1 else None
    mongodb_password_secret = kubernetes.client.CoreV1Api().read_namespaced_secret(namespace="default",
                                                                                   name="ai-arena-password")
    kibana_password_secret = kubernetes.client.CoreV1Api().read_namespaced_secret(namespace="default",
                                                                                  name="elasticsearch-es-elastic-user")
    grafana_credentials_secret = kubernetes.client.CoreV1Api().read_namespaced_secret(namespace="default",
                                                                                      name="ai-arena-grafana")

    print("\n# Frontend")
    if node is not None:
        external_ip = None
        for addr in node.status.addresses:
            if addr.type == "ExternalIP":
                external_ip = addr.address
                break
        if external_ip:
            print(f"http://{external_ip}:31000")
        else:
            print(f"\n# ai-arena-frontend is running on node: {node_name}, but no external IP found.")
    else:
        print("\n# No pod with label app=ai-arena-frontend found in namespace 'default'.")

    mongodb_password = base64.b64decode(mongodb_password_secret.data["mongodb-root-password"]).decode('utf-8')
    print("\n# MongoDB (database)")
    print("Run: kubectl port-forward service/ai-arena-mongodb 27018:27017 --kubeconfig ./kubeconfig.yml")
    print(f"Use any MongoDB client to connect to: mongodb://root:{mongodb_password}@localhost:27018/")

    kibana_password = base64.b64decode(kibana_password_secret.data["elastic"]).decode('utf-8')
    print("\n# Kibana (logs)")
    print(
        "Run: kubectl port-forward service/ai-arena-eck-kibana-kb-http 5601:5601 --kubeconfig ./kubeconfig.yml")
    print(f"username: elastic password: {kibana_password} at https://localhost:5601")

    grafana_username = base64.b64decode(grafana_credentials_secret.data["admin-user"]).decode('utf-8')
    grafana_password = base64.b64decode(grafana_credentials_secret.data["admin-password"]).decode('utf-8')
    print("\n# Grafana (metrics)")
    print(
        "Run: kubectl port-forward service/ai-arena-grafana 3000:80 --kubeconfig ./kubeconfig.yml")
    print(f"username: {grafana_username} password: {grafana_password} at http://localhost:3000")


def retry(func, retries, interval, message):
    while True:
        try:
            return func()
        except Exception as e:
            if retries <= 0:
                raise e
            print(
                f"{message} Retrying in {interval}s, {retries} retries remaining...")
            retries -= 1
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Manage the AI Arena Kubernetes cluster on Azure / Vultr")

    parser.add_argument('api_key', type=str, help='Your Vultr API key')
    subparsers = parser.add_subparsers(dest='command', title='command', help='command to execute')
    parser_install = subparsers.add_parser('install')
    parser_install.add_argument('--password', required=True, type=str, help='MongoDB and Redis password')
    parser_install.add_argument('--name', type=str, default='ai-arena', help='Name of the Kubernetes cluster')
    parser_install.add_argument('--region', type=str, default='ams', help='Region of the Kubernetes cluster')
    parser_install.add_argument('--version', type=str, help='Version of the Kubernetes cluster')
    parser_install.add_argument('--node_pools', type=str,
                                default='[{"node_quantity": 2, "plan": "vc2-2c-4gb", "label": "default-pool"}]',
                                help='Node pools configuration in JSON format')
    parser_install.add_argument('--local_config', type=str, help='Install to a local Kubernetes cluster (minikube)')
    parser_uninstall = subparsers.add_parser('uninstall')
    parser_uninstall.add_argument('--name', type=str, default='ai-arena', help='Name of the Kubernetes cluster')
    subparsers.add_parser('list-plans')
    parser_admin = subparsers.add_parser('admin', help='Provide access to admin sites (MongoDB, Kibana, Grafana, etc.)')
    parser_admin.add_argument('--name', type=str, default='ai-arena', help='Name of the Kubernetes cluster')

    args = parser.parse_args()
    command = args.command
    api_key = args.api_key
    api = VultrAPI(api_key)

    try:
        if command == 'install':
            password = args.password
            name = args.name
            region = args.region
            version = args.version
            node_pools = json.loads(args.node_pools)

            if args.local_config:
                kubeconfig_path = args.local_config
            else:
                clusters = api.list_kubernetes_clusters()
                if not any(cluster['label'] == name for cluster in clusters):
                    if not version:
                        print("Kubernetes version not specified. Retrieving the latest version...")
                        version = api.get_latest_kubernetes_version()
                        print(f"Latest Kubernetes version: {version}")
                    print(f'Cluster "{name}" not found. Creating it...')
                    new_cluster = api.create_kubernetes_cluster(name, region, version, node_pools)
                    cluster_id = new_cluster["id"]
                    print(f'Created cluster "{name}" with ID: {cluster_id}')
                else:
                    cluster_id = next(cluster['id'] for cluster in clusters if cluster['label'] == name)
                    print(f'Cluster "{name}" already exists with ID: {cluster_id}')

                mongo_storage = get_or_create_block_storage(api, region, 'mongodb', 8)
                elasticsearch_storage = get_or_create_block_storage(api, region, 'elasticsearch-data', 10)
                prometheus_storage = get_or_create_block_storage(api, region, 'prometheus', 5)
                grafana_storage = get_or_create_block_storage(api, region, 'grafana', 10)

                # Wait for the cluster and block storage to be ready
                api.wait_for_cluster_ready(cluster_id)
                api.wait_for_block_storage_ready(mongo_storage['id'])
                api.wait_for_block_storage_ready(elasticsearch_storage['id'])

                # Get kubeconfig for the cluster
                kubeconfig_path = "./kubeconfig.yml"
                api.get_kubernetes_kubeconfig(cluster_id, kubeconfig_path)
            kubernetes.config.load_config(config_file=kubeconfig_path)

            retry(lambda: get_or_create_secret("default", "ai-arena-password", {
                'mongodb-root-password': password,
                'redis-password': password,
            }), retries=5, interval=15, message="Kubernetes cluster API call failed. It's probably not available yet.")

            # Install AI Arena using Helm
            helm_install_ai_arena(kubeconfig_path,
                                  {'mongodb': mongo_storage['id'], 'elasticsearch': elasticsearch_storage['id'],
                                   'prometheus': prometheus_storage['id'], 'grafana': grafana_storage['id']})

            retry(print_management_sites, retries=5, interval=15, message="Printing management sites failed.")


        elif command == 'uninstall':
            name = args.name
            clusters = api.list_kubernetes_clusters()
            cluster_to_delete = next((cluster for cluster in clusters if cluster['label'] == name), None)
            if cluster_to_delete:
                print(f'Deleting cluster "{name}" with ID: {cluster_to_delete["id"]}...')
                api.delete_kubernetes_cluster(cluster_to_delete['id'])
                print(f'Deleted cluster "{name}" with ID: {cluster_to_delete["id"]}')
            else:
                print(f'Cluster "{name}" not found. Found clusters:')
                for cluster in clusters:
                    print(f'Label: {cluster["label"]}, ID: {cluster["id"]}')

        elif command == 'list-plans':
            plans = api.list_node_pool_plans()
            if plans:
                print("Available Node Pool Plans:")
                for plan in plans:
                    print(
                        f"ID: {plan['id']}, vCPU Count: {plan['vcpu_count']}, RAM: {plan['ram']}MB, Disk: {plan['disk']}GB, Cost: ${plan['monthly_cost']} per month")
            else:
                print("No plans found.")
        elif command == 'admin':
            name = args.name
            clusters = api.list_kubernetes_clusters()
            if not any(cluster['label'] == name for cluster in clusters):
                print("Cluster not found. Please install the cluster first.")
                return
            cluster_id = next(cluster['id'] for cluster in clusters if cluster['label'] == name)
            kubeconfig_path = "./kubeconfig.yml"
            api.get_kubernetes_kubeconfig(cluster_id, kubeconfig_path)
            kubernetes.config.load_config(config_file=kubeconfig_path)
            print_management_sites()

    except VultrAPIError as e:
        print(e)


if __name__ == "__main__":
    main()
