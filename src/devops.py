import argparse
import json
import subprocess
from vultr_api import VultrAPI, VultrAPIError
import kubernetes
import base64


def get_or_create_block_storage(api, region):
    block = next((block for block in api.list_block_storages() if block['label'] == 'mongodb'), None)
    if block:
        print(f'Block storage "mongodb" already exists with ID: {block["id"]}')
    else:
        print('Block storage "mongodb" not found. Creating one...')
        block = api.create_block_storage('mongodb', region, 8, 'high_perf')
        print(f'Created block storage "mongodb" with ID: {block["id"]}')
    return block


def helm_install_ai_arena(kubeconfig_path, volume_handles):
    print('Installing ai-arena...')
    args = ['helm', 'install', 'ai-arena', 'helm/ai-arena', '-f', 'helm/ai-arena/values.yaml', '--set',
            f'mongodb.volumeHandle={volume_handles["mongodb"]}', '--kubeconfig',
            kubeconfig_path]
    print(' '.join(args))
    subprocess.run(args)


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


def main():
    parser = argparse.ArgumentParser(description="Manage the AI Arena Kubernetes cluster on Vultr")
    parser.add_argument('api_key', type=str, help='Your Vultr API key')
    subparsers = parser.add_subparsers(dest='command', title='command', help='command to execute')
    parser_install = subparsers.add_parser('install')
    parser_install.add_argument('--mongo_pwd', type=str, default='asd', help='MongoDB root password')
    parser_install.add_argument('--name', type=str, default='ai-arena', help='Name of the Kubernetes cluster')
    parser_install.add_argument('--region', type=str, default='ams', help='Region of the Kubernetes cluster')
    parser_install.add_argument('--version', type=str, help='Version of the Kubernetes cluster')
    parser_install.add_argument('--node_pools', type=str,
                                default='[{"node_quantity": 2, "plan": "vc2-2c-4gb", "label": "default-pool"}]',
                                help='Node pools configuration in JSON format')
    parser_uninstall = subparsers.add_parser('uninstall')
    parser_uninstall.add_argument('--name', type=str, default='ai-arena', help='Name of the Kubernetes cluster')
    parser_list_plans = subparsers.add_parser('list_plans')

    args = parser.parse_args()
    command = args.command
    api_key = args.api_key
    api = VultrAPI(api_key)

    try:
        if command == 'install':
            mongo_password = args.mongo_pwd
            name = args.name
            region = args.region
            version = args.version
            node_pools = json.loads(args.node_pools)

            clusters = api.list_kubernetes_clusters()
            cluster_id = None
            cluster_created = False
            if not any(cluster['label'] == name for cluster in clusters):
                if not version:
                    print("Kubernetes version not specified. Retrieving the latest version...")
                    version = api.get_latest_kubernetes_version()
                    print(f"Latest Kubernetes version: {version}")
                print(f'Cluster "{name}" not found. Creating it...')
                new_cluster = api.create_kubernetes_cluster(name, region, version, node_pools)
                cluster_id = new_cluster["id"]
                cluster_created = True
                print(f'Created cluster "{name}" with ID: {cluster_id}')
            else:
                cluster_id = next(cluster['id'] for cluster in clusters if cluster['label'] == name)
                print(f'Cluster "{name}" already exists with ID: {cluster_id}')

            # Ensure block storage "mongodb" exists
            block = get_or_create_block_storage(api, region)

            # Wait for the cluster and block storage to be ready
            api.wait_for_cluster_ready(cluster_id)
            api.wait_for_block_storage_ready(block['id'])

            # Get kubeconfig for the cluster
            kubeconfig_path = "./kubeconfig.yml"
            api.get_kubernetes_kubeconfig(cluster_id, kubeconfig_path)
            kubernetes.config.load_config(config_file=kubeconfig_path)

            get_or_create_secret("default", "ai-arena-mongodb", {
                'mongodb-root-password': mongo_password
            })

            # Install AI Arena using Helm
            helm_install_ai_arena(kubeconfig_path, {'mongodb': block['id']})

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

    except VultrAPIError as e:
        print(e)


if __name__ == "__main__":
    main()
