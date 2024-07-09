import socket
import pip._vendor.requests as requests
import os

def open_listen_socket(host='0.0.0.0', port=8071, accept_timeout=10):
    # Create a socket object
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Set SO_REUSEADDR option
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind the socket to a specific address and port
    server_socket.bind((host, port))

    # Listen for incoming connections
    server_socket.listen(1)

    # Set the accept timeout
    server_socket.settimeout(accept_timeout)

    print(f'Waiting for a connection on port {port}...')
    
    return server_socket

def receive_file(filepath, server_socket, recv_timeout=5):
    try:
        # Accept a connection from a client
        client_socket, client_address = server_socket.accept()
        print('Connected to:', client_address)

        # Set the receive timeout
        client_socket.settimeout(recv_timeout)

        # Receive the file data
        with open(filepath, 'wb') as file:
            while True:
                data = client_socket.recv(1024)
                if not data:
                    break
                file.write(data)

        msg = f"File received, path:{filepath}"
        client_socket.sendall(msg.encode('utf-8'))

    except socket.timeout:
        print(f"Timeout: No connection within ... seconds.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the connection and the socket
        server_socket.close()
        if 'client_socket' in locals():
            client_socket.close()

def download_file_from_url(url, save_path):
    try:
        response = requests.get(url, stream=True, verify=False)
        response.raise_for_status()
        file_name = url.split('/')[-1]

        with open(save_path + file_name, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        file.close()
        
        # Check if the file was downloaded successfully
        if not os.path.isfile(save_path + file_name):
            print(f"File {file_name} not found in the specified path.")
            return False
    except requests.RequestException as e:
        print(f"An error occurred while downloading the file: {e}")
        return False
    finally:
        print(f'File downloaded successfully and saved to {save_path + file_name}')
        return True

if __name__ == "__main__":
    import_path = "/path/to/save/files/"  # Adjust to your import path
    filename = "example.fbx"  # Replace with actual filename
    receive_file(filepath=(import_path + filename), port=8071)
